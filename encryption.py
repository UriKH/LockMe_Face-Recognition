import os
import numpy as np
from cryptography.fernet import Fernet
import winreg

from logger import Logger
from messages import Messages as msg


class Encryption:
    def __init__(self, path, key, suffix, is_db=False):
        self.key = key if not is_db else Encryption.__get_db_key()
        self.fernet = Fernet(self.key)

        clean_path = '.'.join(path.split('.')[:-1])
        self.locked_path = '.'.join([clean_path, 'locked'])
        self.org_path = '.'.join([clean_path, suffix])

    def encrypt_file(self):
        with open(self.org_path, 'rb') as file:
            raw_data = file.read()
            enc_data = self.fernet.encrypt(raw_data)

        with open(self.org_path, 'wb') as f:
            f.write(enc_data)
            Logger(f'{msg.Info.file_encrypt} - path is {self.locked_path}', Logger.warning).log()

        os.rename(self.org_path, self.locked_path)
        return True

    def decrypt_file(self):
        with open(self.locked_path, 'rb') as file:
            enc_data = file.read()
            raw_data = self.fernet.decrypt(enc_data)

        with open(self.locked_path, 'wb') as f:
            f.write(raw_data)
            Logger(f'{msg.Info.file_decrypt} - path is {self.org_path}', Logger.warning).log()

        os.rename(self.locked_path, self.org_path)

    @staticmethod
    def generate_key():
        return Fernet.generate_key()

    @staticmethod
    def __get_db_key():
        """
        Retrieve or generate the database encryption key and save it in the registry
        :return: The database encryption key
        """
        enc_key = None
        try:
            # try getting the key
            reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Software\\LockMe', 0, winreg.KEY_READ)
            enc_key, value_type = winreg.QueryValueEx(reg_key, 'db_key')
            winreg.CloseKey(reg_key)
        except WindowsError:
            Logger(msg.Info.new_db_key, Logger.info).log()

            # create the key
            reg_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, 'Software\\LockMe')

            enc_key = Encryption.generate_key().decode('utf-8')
            value_type = winreg.REG_SZ

            # Set the values for the key
            winreg.SetValueEx(reg_key, 'db_key', 0, value_type, enc_key)
            winreg.CloseKey(reg_key)
        except not WindowsError:
            Logger(msg.Errors.db_no_enc_key, level=Logger.exception).log(Encryption.__get_db_key)

        if enc_key is None:
            Logger(msg.Errors.BUG, level=Logger.error).log()
        return enc_key.encode('utf-8')

    @staticmethod
    def key_from_embedding(embedding):
        """
        Generate a 128 bits key from 512 float vector
        :param embedding: A 512 float vector representing an image
        :return: The key generated from the vector
        """
        if len(embedding) < 512:
            Logger(msg.Errors.BUG, Logger.exception).log()

        embedding = [embedding[i] + embedding[i+1] for i in range(stop=512, step=2)]
        bin_embedding = (np.array(embedding) > 0)
        binary_string = ''.join(str(bit) for bit in bin_embedding)
        integer = int(binary_string, 2)
        key = integer.to_bytes(128, byteorder='big')
        return key
