const cameraStatus = document.getElementById('camera-status');
const cameraPreview = document.getElementById('camera-preview');
const startCameraBtn = document.getElementById('start-camera');
const captureBtn = document.getElementById('capture-image');
const retakeBtn = document.getElementById('retake-image');
const captureInput = document.getElementById('capture');
const authForm = document.getElementById('auth-form');

let stream = null;
let captureDataUrl = null;
let isSubmitting = false;

function setStatus(message, type = 'info') {
  if (!cameraStatus) return;
  cameraStatus.textContent = message;
  cameraStatus.className = `message-box ${type}`;
}

async function startCamera() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    setStatus('This browser does not support camera access.', 'error');
    return;
  }

  stopCamera();
  captureDataUrl = null;
  if (captureInput) captureInput.value = '';
  if (cameraPreview) cameraPreview.src = '';
  if (captureBtn) captureBtn.disabled = true;
  if (retakeBtn) retakeBtn.disabled = true;
  setStatus('Waiting for camera permission…', 'info');

  try {
    let streamAttempt = null;
    try {
      streamAttempt = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user' },
        audio: false,
      });
    } catch (constraintErr) {
      // Graceful fallback for mobile or browsers that reject the facingMode constraint
      streamAttempt = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false,
      });
    }
    stream = streamAttempt;

    if (cameraPreview) {
      cameraPreview.srcObject = stream;
      await cameraPreview.play();
    }

    const trackSettings = stream.getVideoTracks()[0]?.getSettings();
    const dimensions = trackSettings?.width && trackSettings?.height
      ? ` (${trackSettings.width} × ${trackSettings.height})`
      : '';
    setStatus(`Camera ready${dimensions}. Position your eye in the frame and capture.`, 'success');
    if (captureBtn) captureBtn.disabled = false;
  } catch (error) {
    stopCamera();
    const message = error.name === 'NotAllowedError'
      ? 'Camera permission was denied. Allow camera access in your browser settings and try again.'
      : error.name === 'NotFoundError'
        ? 'No camera was found. Connect or enable a camera and try again.'
        : 'Camera access failed. Check that the camera is connected and not being used by another app.';
    setStatus(message, 'error');
  }
}

function stopCamera() {
  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }

  if (cameraPreview) {
    cameraPreview.srcObject = null;
  }
}

function captureFrame() {
  if (!cameraPreview || !cameraPreview.videoWidth) {
    setStatus('Camera is not ready yet. Please start the camera first.', 'error');
    return false;
  }

  const canvas = document.createElement('canvas');
  canvas.width = cameraPreview.videoWidth;
  canvas.height = cameraPreview.videoHeight;

  const context = canvas.getContext('2d');
  if (!context) {
    setStatus('Could not capture an image. Please restart the camera and try again.', 'error');
    return false;
  }
  try {
    context.drawImage(cameraPreview, 0, 0, canvas.width, canvas.height);
    captureDataUrl = canvas.toDataURL('image/png');
  } catch (error) {
    setStatus('Camera capture failed. Restart the camera and try again.', 'error');
    return false;
  }

  if (cameraPreview) {
    cameraPreview.srcObject = null;
    cameraPreview.src = captureDataUrl;
  }

  setStatus(`Image captured (${canvas.width} × ${canvas.height}, PNG). Submit it for iris verification.`, 'success');
  if (captureBtn) captureBtn.disabled = true;
  if (retakeBtn) retakeBtn.disabled = false;

  if (captureInput) {
    const blob = dataURLtoBlob(captureDataUrl);
    const file = new File([blob], 'iris_capture.png', { type: 'image/png' });
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    captureInput.files = dataTransfer.files;
  }

  stopCamera();
  return Boolean(captureInput && captureInput.files.length);
}

function dataURLtoBlob(dataURL) {
  const parts = dataURL.split(',');
  const mime = parts[0].match(/:(.*?);/)[1];
  const binary = atob(parts[1]);
  const array = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    array[i] = binary.charCodeAt(i);
  }
  return new Blob([array], { type: mime });
}

if (startCameraBtn) {
  startCameraBtn.addEventListener('click', startCamera);
}

if (captureBtn) {
  captureBtn.addEventListener('click', captureFrame);
  captureBtn.disabled = true;
}

if (retakeBtn) {
  retakeBtn.addEventListener('click', () => {
    captureDataUrl = null;
    if (cameraPreview) {
      cameraPreview.src = '';
    }
    if (captureInput) captureInput.value = '';
    setStatus('Ready to capture a new image.', 'info');
    startCamera();
  });
  retakeBtn.disabled = true;
}

if (captureInput) {
  captureInput.addEventListener('change', () => {
    const [selectedFile] = captureInput.files;
    if (!selectedFile) return;

    stopCamera();
    if (cameraPreview) {
      if (selectedFile.type && !selectedFile.type.startsWith('image/')) {
        cameraPreview.src = '';
        setStatus('Please select a valid image file (PNG or JPEG).', 'error');
        return;
      }
      const reader = new FileReader();
      reader.onload = (e) => {
        cameraPreview.srcObject = null;
        cameraPreview.src = e.target.result;
      };
      reader.readAsDataURL(selectedFile);
    }
    setStatus(`Image selected: ${selectedFile.name}. Verify the preview or submit for iris verification.`, 'success');
    if (captureBtn) captureBtn.disabled = true;
    if (retakeBtn) retakeBtn.disabled = false;
  });
}

if (authForm) {
  const submitButton = authForm.querySelector('button[type="submit"]');
  if (submitButton) {
    submitButton.addEventListener('pointerdown', () => {
      if (authForm.dataset.autoCapture === 'true' && (!captureInput || !captureInput.files.length)) {
        captureFrame();
      }
    });
  }

  authForm.addEventListener('submit', (event) => {
    if (isSubmitting) {
      event.preventDefault();
      return;
    }

    if (authForm.dataset.autoCapture === 'true' && (!captureInput || !captureInput.files.length)) {
      if (!captureFrame()) {
        event.preventDefault();
        return;
      }
    }

    if (!captureInput || !captureInput.files.length) {
      event.preventDefault();
      setStatus('Choose an iris image or capture one with the camera before continuing.', 'error');
      return;
    }

    isSubmitting = true;
    setStatus('Processing your iris. Please wait…', 'info');
    const submitButton = authForm.querySelector('button[type="submit"]');
    if (submitButton) {
      if (!submitButton.dataset.originalText) {
        submitButton.dataset.originalText = submitButton.textContent;
      }
      submitButton.disabled = true;
      submitButton.textContent = 'Processing…';
    }
  });
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    stopCamera();
  }
});

window.addEventListener('pagehide', stopCamera);
window.addEventListener('beforeunload', stopCamera);

window.addEventListener('pageshow', () => {
  isSubmitting = false;
  if (authForm) {
    const submitButton = authForm.querySelector('button[type="submit"]');
    if (submitButton) {
      submitButton.disabled = false;
      if (submitButton.dataset.originalText) {
        submitButton.textContent = submitButton.dataset.originalText;
      }
    }
  }
});
