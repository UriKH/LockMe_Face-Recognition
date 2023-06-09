import cv2 as cv
from terminal_ui.keys import KeyMap
from utils.messages import Messages as msg
from utils.logger import Logger


class Camera:
    """
    Class for handling camera operations in the terminal interface
    """
    default_size = 500
    window_name = 'cam view'
    freeze_color = (0, 255, 0)
    retake_time = 2

    def __init__(self):
        """
        Initialize the Camera for scanning
        """
        self._v_cap = cv.VideoCapture(0)
        if self._v_cap is None:
            Logger(msg.Errors.no_cam, Logger.error).log()

        self._pic = None
        self._last_frame = None

    def run(self):
        """
        Run the camera UI to capture an image of the user
        """
        Logger(msg.Info.take_pic, Logger.message).log()
        Logger(msg.Info.pic_instruction, Logger.warning).log()

        while True:
            self.read_stream()
            image = self.prepare_presentation()
            cv.imshow(Camera.window_name, image)
            key = cv.waitKey(1)

            # taking the image
            if key == ord(KeyMap.take_pic):
                cv.imshow(Camera.window_name, self.freeze())
                Logger(msg.Info.retake_pic, Logger.message).log()

                while True:
                    cv.imshow(Camera.window_name, self.freeze())
                    key = cv.waitKey(1)

                    if key == ord(KeyMap.close_cam):    # close the camera
                        Logger(msg.Info.pic_taken, Logger.message).log()
                        cv.destroyAllWindows()
                        return
                    elif key == ord(KeyMap.retake_pic):   # retake picture
                        Logger(msg.Info.take_pic, Logger.message).log()
                        break

    def read_stream(self):
        """
        Read a frame from the camera
        """
        frame = None
        try:
            ret, frame = self._v_cap.read()
        except Exception as e:
            Logger(f'{e}. Please rerun the program', Logger.error).log()
        self._pic = frame if frame is not None else self._last_frame
        self._last_frame = self._pic

    def prepare_presentation(self):
        """
        Resize image for later presentation
        """
        image = self._pic.copy()
        h, w, _ = image.shape
        cv.resize(image, (int(Camera.default_size * w/h), Camera.default_size))
        return image

    def freeze(self):
        """
        Create a frozen frame representation
        """
        image = self.prepare_presentation()
        cv.rectangle(image, (0, 0), (image.shape[1], image.shape[0]), Camera.freeze_color, 2)
        return image

    def get_pic(self):
        return self._pic.copy()
