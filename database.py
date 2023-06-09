import sqlite3
import os
import bz2 as bz
import struct
from tqdm import tqdm
import numpy as np
import cv2 as cv

from encryption import Encryption
from utils.logger import Logger
from utils.messages import Messages as msg
from terminal_ui.keys import KeyMap
from model.SNN import Net
# could not import the User bcs of circular input...


class Database:
    parent_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'databases')
    org_path = os.path.join(parent_dir, r'database.db')
    locked_path = os.path.join(parent_dir, r'database.locked')
    file_state_open = 1
    file_state_locked = 0

    def __init__(self):
        if not os.path.exists(Database.parent_dir):
            os.mkdir(Database.parent_dir)
        self.enc_track = Encryption(Database.locked_path, None, 'db', is_db=True)   # track encryption of the database
        if os.path.exists(Database.locked_path):
            self.enc_track.decrypt_file()

        self.connection = sqlite3.connect(Database.org_path)    # connect to the database
        self.cursor = self.connection.cursor()

        self.__init_tables()    # create the tables

    def __del__(self):
        """
        Encrypt the DB before termination
        """
        self.lock_all_files()
        self.connection.close()
        self.enc_track.encrypt_file()

    def __init_tables(self):
        """
        Initiate the database's tables if needed
        """
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS users("
            "uid INTEGER PRIMARY KEY,"
            "user_embedding TEXT,"
            "user_image TEXT)"
        )
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS files("
            "file_path TEXT PRIMARY KEY,"
            "suffix TEXT,"
            "uid INTEGER,"
            "file TEXT,"
            "file_state INTEGER)"
        )
        self.connection.commit()

    @staticmethod
    def _compress_data(data):
        """
        Compress data using the BZ2 compression algorithm
        :param data: data to compress
        :return: the compressed data
        """
        compressor = bz.BZ2Compressor()
        compressed_data = compressor.compress(data) + compressor.flush()
        return compressed_data

    @staticmethod
    def _decompress_data(data):
        """
        Decompress data using the BZ2 compression algorithm
        :param data: compress BZ2 data
        :return: the decompressed data
        """
        decompressed_data = bz.decompress(data).decode()
        return decompressed_data

    @staticmethod
    def _embedding_to_byte(embedding):
        """
        Transform a float list embedding to bytes type
        :param embedding: the embedding vector
        :return: the bytes type embedding
        """
        embedding_b = bytearray(struct.pack(f'{Net.embedding_size}f', *embedding))
        return embedding_b

    @staticmethod
    def byte_to_embedding(embedding_b):
        """
        Transform bytes type embedding to a float list
        :param embedding_b: the bytes type embedding
        :return: the vectorized embedding
        """
        embedding = struct.unpack(f'{Net.embedding_size}f', embedding_b)
        return embedding

    def _recover(self, path, comp_file, key, locked_path):
        """
        Recover a file from the database
        :param path: path to the file as it was originally add to the system
        :param comp_file: the compressed file as it is the database
        :param key: key to the fernet encryption
        :param locked_path: the path to the file with the locked suffix
        """
        with open(path, 'wb') as fd:
            enc_file = Database._decompress_data(comp_file).encode('utf-8')
            recovered_data = Encryption.decrypt_data(enc_file, key)
            fd.write(recovered_data)
        if os.path.exists(locked_path):
            os.remove(locked_path)
        self.cursor.execute("UPDATE files SET file_state = ? WHERE file_path = ?",
                            (Database.file_state_open, Database.raw_path(path)))
        self.connection.commit()
        Logger(msg.Info.file_recovered + f' {path}', Logger.info).log()

    def fetch_users(self):
        """
        Fetch all user IDs and their correlated face embeddings from the DB
        :return: the retrieved data
        """
        self.cursor.execute("SELECT * FROM users")
        return self.cursor.fetchall()

    def fetch_all_ids(self):
        """
        Fetch all user IDs from the DB
        :return: the retrieved IDs
        """
        self.cursor.execute("SELECT uid FROM users")
        return self.cursor.fetchall()

    def fetch_user_data(self, uid=None):
        """
        Retrieve the user's data
        :param uid: the current user ID
        :return: the user's data as a dictionary:
            {'file_path': [...], 'suffix': [...], 'user_id': [...], 'file': [...], 'file_state': [...]}
        """
        if uid is None:
            self.cursor.execute("SELECT file_path, suffix, uid, file, file_state FROM files")
        else:
            self.cursor.execute("SELECT file_path, suffix, uid, file, file_state FROM files WHERE uid = ?", (uid,))
        data = self.cursor.fetchall()
        data_dict = {'file_path': [], 'suffix': [], 'user_id': [], 'file': [], 'file_state': []}
        for row in data:
            data_dict['file_path'].append(row[0])
            data_dict['suffix'].append(row[1])
            data_dict['user_id'].append(row[2])
            data_dict['file'].append(row[3])
            data_dict['file_state'].append(row[4])
        return data_dict

    def create_new_user(self, user):
        """
        ADD a new user to the system
        :param user: a User object
        :return: the new user's ID
        """
        embedding_b = Database._embedding_to_byte(user.embedding)
        uids = self.fetch_all_ids()
        max_id = 0
        for row in uids:     # because UIDs is of shape (n, )
            uid = row[0]
            if uid > max_id:
                max_id = uid

        image = user.img_data.image.copy()
        self.cursor.execute("INSERT INTO users (uid, user_embedding, user_image) VALUES (?,?,?)",
                            (max_id + 1, embedding_b, image.tobytes()))
        self.connection.commit()
        return max_id + 1

    def get_user_embedding_as_key(self, uid: int):
        """
        Retrieve the user face embedding from the DB and generate the key from it
        :param uid: the user ID
        :return: the generated fernet key
        """
        self.cursor.execute("SELECT user_embedding FROM users WHERE uid = ?", (uid,))
        embedding_b = self.cursor.fetchall()[0][0]
        embedding = Database.byte_to_embedding(embedding_b)
        key = Encryption.key_from_embedding(list(embedding))
        return key

    def __validate_action_on_file(self, path: str, user):
        """
        Check if the file is accessible and the user could change it
        :param path: path to the file without suffix
        :param user: a User object
        :return: True if file is accessible else False
        """
        self.cursor.execute("SELECT file_path, uid, suffix, file, file_state FROM files")
        res = self.cursor.fetchall()
        suffix = None
        file_state = None
        comp_file = None

        path = Database.formalize_path(path)
        found = False
        for row in res:
            if path == Database.formalize_path(row[0]):
                if row[1] != user.uid:
                    Logger(msg.Errors.access_denied + f' to file {path}', Logger.inform).log()
                    return False, None
                found = True
                suffix = row[2]
                comp_file = row[3]
                file_state = row[4]
                break
        if not found:
            Logger(msg.Errors.failed_removal, Logger.inform).log()
            return False, None
        return True, {'file_path': path, 'uid': user.uid, 'suffix': suffix, 'file': comp_file, 'file_state': file_state}

    def add_file(self, path: str, user) -> bool:
        """
        Add a file to the DB
        :param path: the path to the file to be added
        :param user: a User object
        :return: True if file was successfully added to the DB
        """
        # check if the file is already in the database
        self.cursor.execute("SELECT file_path, uid FROM files")
        res = self.cursor.fetchall()
        path = Database.formalize_path(path)
        for row in res:
            if Database.raw_path(path) == row[0]:
                Logger(msg.Errors.failed_insertion + f' - owner ID: {row[1]}', Logger.inform).log()
                return False

        if '.' in path:
            suffix = path.split('.')[-1]
        else:
            suffix = 'no suffix'

        if not os.path.isfile(path):
            Logger(msg.Errors.not_a_file, Logger.warning).log()
            return False

        with open(path, 'rb') as fd:
            data = fd.read()

        key = self.get_user_embedding_as_key(user.uid)

        if suffix == 'locked':
            Logger(msg.Errors.unsupported_file_type + f' (.{suffix})', Logger.inform).log()
            return False

        enc_data = Encryption.encrypt_data(data, key)
        comp_data = Database._compress_data(enc_data)
        self.cursor.execute(
            "INSERT INTO files (file_path, suffix, uid, file, file_state) VALUES (?, ?, ?, ?, ?)",
            (Database.raw_path(path), suffix, user.uid, comp_data, Database.file_state_open))
        self.connection.commit()
        Logger(msg.Info.file_added + f' {path}', Logger.info).log()
        return True

    def remove_file(self, path: str, user) -> bool:
        """
        Remove a file from the DB
        :param path: the path to the file to remove
        :param user: a User object
        :return: True if the file removed successfully
        """
        # check if action is valid on the file
        path = Database.formalize_path(path)
        valid, db_data = self.__validate_action_on_file(Database.raw_path(path), user)
        if not valid:
            return False

        self.decrypt_user_file(path, user, db_data)

        # delete the file from the database
        self.cursor.execute("DELETE FROM files WHERE file_path = ?", (Database.raw_path(path),))
        self.connection.commit()
        Logger(msg.Info.file_removed + f' {path}', Logger.info).log()
        return True

    def lock_file(self, path: str, user) -> bool:
        """
        Encrypt a file and update the backup to the latest version
        :param path: the path to the file
        :param user: a User object
        :return: True if encrypted successfully
        """
        # check if action is valid on the file
        path = Database.formalize_path(path)
        valid, db_data = self.__validate_action_on_file(Database.raw_path(path), user)
        if not valid:
            return False

        # file is already locked
        if db_data['file_state'] == Database.file_state_locked:
            Logger(msg.Info.file_encrypt).log()
            return True

        path = '\\'.join(path.split('/') if path.split('\\')[0] == path else path.split('\\'))
        key = self.get_user_embedding_as_key(db_data['uid'])
        # encrypt the file
        file_enc = Encryption(path, key, db_data['suffix'])
        locked_path = file_enc.locked_path

        try:
            enc_data = file_enc.encrypt_file()
            comp_data = Database._compress_data(enc_data)

            # change the file state in the database and update to the latest version
            self.cursor.execute("UPDATE files SET file_state = ?, file = ? WHERE file_path = ?",
                                (Database.file_state_locked, comp_data, Database.raw_path(path)))
            self.connection.commit()
            return True
        except:
            self._recover(f'{Database.raw_path(path)}.{db_data["suffix"]}', db_data['file'], key, locked_path)
            return False

    def unlock_file(self, path: str, user) -> bool:
        """
        Decrypts a file
        :param path: path to the file
        :param user: a User object
        """
        # check if action is valid on the file
        path = Database.formalize_path(path)
        valid, db_data = self.__validate_action_on_file(Database.raw_path(path), user)
        if not valid:
            return False

        # file is already unlocked
        if db_data['file_state'] == Database.file_state_open:
            Logger(msg.Info.file_decrypt).log()
            return True

        path = '\\'.join(path.split('/') if path.split('\\')[0] == path else path.split('\\'))
        self.decrypt_user_file(path, user, db_data)

        # change the file state in the database
        self.cursor.execute("UPDATE files SET file_state = ? WHERE file_path = ?",
                            (Database.file_state_open, Database.raw_path(path)))
        self.connection.commit()
        return True

    def decrypt_user_file(self, path: str, user, db_data):
        """
        Decrypts a locked file for a user
        :param path: path to the file
        :param user: a User object
        :param db_data: the database's data on the file
        """
        key = self.get_user_embedding_as_key(user.uid)
        locked_path = None
        path = Database.formalize_path(path)

        # decrypt the file if encrypted
        try:
            if db_data['file_state'] == Database.file_state_locked:
                file_enc = Encryption(path, key, db_data['suffix'])
                locked_path = file_enc.locked_path
                file_enc.decrypt_file()
        except:
            self._recover(f'{Database.raw_path(path)}.{db_data["suffix"]}', db_data['file'], key, locked_path)

    def lock_all_files(self, uid: int = None):
        """
        Lock all files owned by the specified ID. If no ID is specified, lock all the system files
        :param uid: user ID
        """
        data_dict = self.fetch_user_data(uid)
        if len(data_dict['file_path']) == 0:    # prevent from running tqdm
            return

        for i, path in zip(
                tqdm(range(len(data_dict['file_path'])), desc=msg.Load.locking_files),
                data_dict['file_path']):
            # file is already locked
            if data_dict['file_state'][i] == Database.file_state_locked:
                continue

            if uid is not None:
                if uid != data_dict['user_id'][i]:
                    continue

            # encrypt the file
            path = Database.formalize_path(path)
            key = self.get_user_embedding_as_key(data_dict['user_id'][i])
            file_enc = Encryption(f'{path}.{data_dict["suffix"][i]}', key, data_dict['suffix'][i])
            enc_data = file_enc.encrypt_file(log=False)
            comp_data = Database._compress_data(enc_data)

            # change the file state in the database and update to latest changes
            self.cursor.execute("UPDATE files SET file_state = ?, file = ? WHERE file_path = ?",
                                (Database.file_state_locked, comp_data, path))
            self.connection.commit()
        print()     # this is a bug fix of tqdm covering the input line

    def unlock_all_files(self, uid: int = None):
        """
        Unlock all files owned by the specified ID. If no ID is specified, unlock all the system files
        :param uid: user ID
        """
        data_dict = self.fetch_user_data(uid)
        if len(data_dict['file_path']) == 0:    # prevent from running tqdm
            return

        for i, path in zip(
                tqdm(range(len(data_dict['file_path'])), desc=msg.Load.unlocking_files),
                data_dict['file_path']):
            # file is already locked
            if data_dict['file_state'][i] == Database.file_state_open:
                continue

            if uid is not None:
                if uid != data_dict['user_id'][i]:
                    continue

            # encrypt the file
            path = Database.formalize_path(path)
            key = self.get_user_embedding_as_key(data_dict['user_id'][i])
            file_enc = Encryption(f'{path}.{data_dict["suffix"][i]}', key, data_dict['suffix'][i])
            file_enc.decrypt_file(log=False)

            # change the file state in the database
            self.cursor.execute("UPDATE files SET file_state = ? WHERE file_path = ?",
                                (Database.file_state_open, path))
            self.connection.commit()
        print()  # this is a bug fix of tqdm covering the input line

    def delete_user(self, uid: int, sure: bool = False) -> bool:
        """
        Delete a user from the system
        :param uid: the user ID
        :param sure: if user is sure to delete all files
        :return: True if deleted and False if aborted
        """
        Logger(msg.Requests.delete_user, level=Logger.message).log()
        if sure:
            self.unlock_all_files(uid)
            self.cursor.execute("DELETE FROM files WHERE uid = ?", (uid,))
            self.cursor.execute("DELETE FROM users WHERE uid = ?", (uid,))
            self.connection.commit()
            Logger(msg.Info.user_deleted + f' - ID: {uid}', Logger.warning).log()
            return True

        while True:
            ans = input('>>> ')
            if not ans.isalpha():
                continue
            ans = ans.lower()
            if ans == KeyMap.yes:
                self.unlock_all_files(uid)
                self.cursor.execute("DELETE FROM files WHERE uid = ?", (uid,))
                self.cursor.execute("DELETE FROM users WHERE uid = ?", (uid,))
                self.connection.commit()
                Logger(msg.Info.user_deleted + f' - ID: {uid}', Logger.warning).log()
                return True
            elif ans == KeyMap.no:
                return False

    def recover_file(self, path: str, user) -> bool:
        """
        Recover a file from latest saved version
        :param path: path to the file
        :param user: a User object
        """
        # check if action is valid on the file
        path = Database.formalize_path(path)
        valid, db_data = self.__validate_action_on_file(Database.raw_path(path), user)
        if not valid:
            return False

        key = self.get_user_embedding_as_key(user.uid)
        file_enc = Encryption(f'{Database.raw_path(path)}.{db_data["suffix"]}', key, db_data['suffix'])
        self._recover(f'{Database.raw_path(path)}.{db_data["suffix"]}', db_data['file'], key, file_enc.locked_path)
        return True

    def get_user_image(self, uid, dims, convert_rgb=False):
        self.cursor.execute('SELECT user_image FROM users WHERE uid = ?', (uid,))
        result = self.cursor.fetchone()
        image_bytes = result[0]
        image_np = np.frombuffer(image_bytes, dtype=np.uint8).reshape(dims)
        if convert_rgb:
            image_np = cv.cvtColor(image_np, cv.COLOR_BGR2RGB)
        return image_np

    @staticmethod
    def formalize_path(path):
        return path if path.split('\\')[0] != path else '\\'.join(path.split('/'))

    @staticmethod
    def raw_path(path):
        return '.'.join(path.split('.')[:-1])
