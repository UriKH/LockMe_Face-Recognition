import numpy as np
import torch

from CNN.image_process import Image
from CNN.initialize import Init
from database import Database


class User:
    dist_thresh = 0.7

    def __init__(self, user_img):
        self.img_data = Image(user_img)
        self.embedding = self.img_data.choose_face()
        self.uid = None
        self.valid = self.login()

    def check_similarity(self, data):
        min_dist = 100.
        identity = None

        for uid, e in data:
            dist = (torch.tensor(list(e)) - self.embedding).norm()
            if dist < min_dist:
                min_dist = dist
                identity = uid
        if min_dist > User.dist_thresh:
            identity = None
        return identity

    def login(self):
        data = Init.database.fetch_users()
        for i, user in enumerate(data):
            data[i] = list(data[i])
            data[i][1] = Database._byte_to_embedding(user[1])
        self.uid = self.check_similarity(data)
        return self.uid is not None
