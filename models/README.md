# Detection / recognition models

These models are optional. The iris pipeline works without them; when present,
the app uses YuNet for face and eye localization and SFace as a second-factor
face check for 1:1 login.

| File | Purpose | License |
| --- | --- | --- |
| `face_detection_yunet_2023mar.onnx` | YuNet face detector with 5 landmarks | MIT (OpenCV Zoo) |
| `face_recognition_sface_2021dec.onnx` | SFace 128-D face embedding model | MIT (OpenCV Zoo) |

Sources:

- <https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet>
- <https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface>

Both files are loaded through OpenCV (`cv2.FaceDetectorYN` and
`cv2.FaceRecognizerSF`), so no extra Python package is required. Do not commit
face images or enrollment databases; only the model weights belong here.
