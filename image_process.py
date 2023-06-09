import cv2 as cv
import numpy as np

from utils.initialize import Init
from utils.logger import Logger
from utils.messages import Messages as msg
from model.dataset import ModelDataset
from camera_runner import Camera


class Image(Init):
    """
    This class is used to compute and retrieve all the data from the image taken by the user
    """
    conf_thresh = 0.9

    def __init__(self, image):
        super().__init__()
        self.image = cv.cvtColor(image, cv.COLOR_BGR2RGB)
        self.embeddings_dict = {}

        self.create_embeddings()
        self.image = cv.cvtColor(self.image, cv.COLOR_RGB2BGR)
        self.x_pos, self.y_pos = None, None

    @Logger(msg.Info.faces_located, Logger.info).time_it
    def __get_coords(self):
        """
        Get the faces bounding boxes in the image
        :return: a list of the bounding boxes
        """
        boxes, conf = self.mtcnn.detect(self.image)
        boxes = boxes.astype(int)
        new_boxes = []
        for i, box in enumerate(boxes):
            if conf[i] < Image.conf_thresh:
                continue
            x1, y1, x2, y2 = box
            h, w, _ = self.image.shape
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(w, x2)
            y2 = min(h, y2)
            box = x1, y1, x2, y2
            new_boxes.append(box)
        return new_boxes

    @Logger(msg.Info.embeddings_generated, Logger.info).time_it
    def create_embeddings(self):
        """
        Create embeddings of the detected faces
        """
        for box in self.__get_coords():
            x_aligned = ModelDataset.create_image(self.image, box)
            x_aligned = cv.cvtColor(x_aligned, cv.COLOR_GRAY2BGR)
            processed = self.net.preprocess_image(x_aligned)
            embedding = self.net.forward_once(processed.unsqueeze(0).to(self.device))
            self.embeddings_dict[tuple(box)] = np.squeeze(embedding.detach().numpy())

    def choose_face(self):
        """
        Choose a face to run on
        """
        if len(self.embeddings_dict.keys()) == 1:
            Logger(msg.Info.single_face, Logger.warning).log()
            return list(self.embeddings_dict.values())[0]

        def mouse_callback(event, x, y, flags, params):
            if event == cv.EVENT_LBUTTONUP or event == cv.EVENT_RBUTTONUP:
                self.x_pos = x
                self.y_pos = y
                Logger(f'mouse clicked ({x}, {y})', Logger.info).log()

        cv.namedWindow(Camera.window_name, cv.WINDOW_NORMAL)
        cv.setMouseCallback(Camera.window_name, mouse_callback)

        # draw an index box of the face
        new_img = self.image.copy()
        for i, (x1, y1, x2, y2) in enumerate(self.embeddings_dict.keys()):
            cv.rectangle(new_img, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv.rectangle(new_img, (x1 - 1, y2 - 35), (x2 + 1, y2), (0, 0, 255), cv.FILLED)
            cv.putText(new_img, str(i + 1), (x1 + 7, y2 - 5), cv.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

        Logger(msg.Requests.face_index, Logger.message).log()
        while True:
            cv.imshow(Camera.window_name, new_img)
            cv.setMouseCallback(Camera.window_name, mouse_callback)
            cv.waitKey(1)
            if self.x_pos is None and self.y_pos is None:
                continue
            for i, (x1, y1, x2, y2) in enumerate(self.embeddings_dict.keys()):
                if x1 <= self.x_pos <= x2 and y1 <= self.y_pos <= y2:
                    cv.destroyAllWindows()
                    return list(self.embeddings_dict.values())[i]
            self.x_pos, self.y_pos = None, None
            Logger(msg.Errors.no_face_click, Logger.warning).log()
