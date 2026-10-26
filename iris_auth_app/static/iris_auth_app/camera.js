const cameraStatus = document.getElementById('camera-status');
const cameraPreview = document.getElementById('camera-preview');
const cameraPanel = document.getElementById('camera-panel');
const scannerOverlay = document.getElementById('scanner-overlay');
const scannerBadge = document.getElementById('scanner-badge');
const startCameraBtn = document.getElementById('start-camera');
const captureBtn = document.getElementById('capture-image');
const retakeBtn = document.getElementById('retake-image');
const manualScanBtn = document.getElementById('manual-scan-btn');
const captureInput = document.getElementById('capture');
const authForm = document.getElementById('auth-form');

let stream = null;
let captureDataUrl = null;
let isSubmitting = false;
let liveScanTimer = null;
let liveScanInFlight = false;
let liveAttemptCount = 0;

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
  liveAttemptCount = 0;
  if (captureInput) captureInput.value = '';
  if (cameraPreview) cameraPreview.src = '';
  if (captureBtn) captureBtn.disabled = true;
  if (retakeBtn) retakeBtn.disabled = true;
  setStatus('Starting camera… Please allow camera permission if prompted.', 'info');

  try {
    let streamAttempt = null;
    try {
      streamAttempt = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: 'user',
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      });
    } catch (constraintErr) {
      streamAttempt = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false,
      });
    }
    stream = streamAttempt;

    if (cameraPreview) {
      cameraPreview.muted = true;
      cameraPreview.playsInline = true;
      cameraPreview.setAttribute('playsinline', '');
      cameraPreview.setAttribute('webkit-playsinline', '');
      cameraPreview.srcObject = stream;
      await cameraPreview.play();
    }

    if (cameraPanel) {
      cameraPanel.classList.remove('matched');
      cameraPanel.classList.add('scanning');
    }

    if (captureBtn) captureBtn.disabled = false;

    if (authForm && authForm.dataset.autoCapture === 'true') {
      if (scannerBadge) scannerBadge.textContent = 'Live Scanning active…';
      setStatus('Live Iris Scanner is running hands-free! Align your eyes in the reticle.', 'success');
      startLiveScanner();
    } else {
      setStatus('Camera ready. Position your eye in the frame and capture.', 'success');
    }
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
  stopLiveScanner();

  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }

  if (cameraPreview) {
    cameraPreview.srcObject = null;
  }

  if (cameraPanel && !isSubmitting) {
    cameraPanel.classList.remove('scanning');
  }
}

function startLiveScanner() {
  stopLiveScanner();
  liveScanInFlight = false;
  liveAttemptCount = 0;
  // Poll live video frame every 550ms
  liveScanTimer = setInterval(scanCurrentFrame, 550);
}

function stopLiveScanner() {
  if (liveScanTimer) {
    clearInterval(liveScanTimer);
    liveScanTimer = null;
  }
  liveScanInFlight = false;
}

function scanCurrentFrame() {
  if (!stream || !cameraPreview || !cameraPreview.videoWidth || isSubmitting || liveScanInFlight) {
    return;
  }

  liveScanInFlight = true;
  liveAttemptCount += 1;

  const canvas = document.createElement('canvas');
  const maxDim = 960;
  let w = cameraPreview.videoWidth;
  let h = cameraPreview.videoHeight;
  if (w > maxDim || h > maxDim) {
    if (w > h) {
      h = Math.round(h * (maxDim / w));
      w = maxDim;
    } else {
      w = Math.round(w * (maxDim / h));
      h = maxDim;
    }
  }
  canvas.width = w;
  canvas.height = h;

  const context = canvas.getContext('2d');
  if (!context) {
    liveScanInFlight = false;
    return;
  }

  context.drawImage(cameraPreview, 0, 0, w, h);

  canvas.toBlob(async (blob) => {
    if (!blob || !stream || isSubmitting) {
      liveScanInFlight = false;
      return;
    }

    try {
      const formData = new FormData();
      formData.append('capture', blob, 'live_iris.png');
      formData.append('ajax', 'true');

      const csrfInput = authForm ? authForm.querySelector('input[name="csrfmiddlewaretoken"]') : null;
      if (csrfInput) {
        formData.append('csrfmiddlewaretoken', csrfInput.value);
      }

      const targetUrl = (authForm && authForm.action) ? authForm.action : window.location.pathname;
      const response = await fetch(targetUrl, {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json',
        },
        body: formData,
      });

      if (!stream) {
        liveScanInFlight = false;
        return;
      }

      if (response.ok) {
        const data = await response.json();
        if (data.status === 'success') {
          isSubmitting = true;
          stopCamera();
          if (cameraPanel) {
            cameraPanel.classList.remove('scanning');
            cameraPanel.classList.add('matched');
          }
          if (scannerBadge) {
            scannerBadge.textContent = '✓ Verified!';
          }
          setStatus(`Iris verified for ${data.display_name || data.username || 'user'}. Logging in…`, 'success');
          setTimeout(() => {
            window.location.href = data.redirect_url || '/dashboard/';
          }, 300);
          return;
        } else if (data.status === 'retry') {
          if (scannerBadge) {
            scannerBadge.textContent = `Scanning live (${liveAttemptCount})… Keep steady`;
          }
        }
      } else if (response.status === 429) {
        if (scannerBadge) scannerBadge.textContent = 'Rate limit cooling…';
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    } catch (err) {
      // Non-fatal network glitch; continue scanning
    } finally {
      liveScanInFlight = false;
    }
  }, 'image/png');
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

if (cameraPanel) {
  cameraPanel.addEventListener('click', () => {
    if (!stream) {
      startCamera();
    }
  });
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
      setStatus('Choose an iris image or start the live camera before continuing.', 'error');
      return;
    }

    isSubmitting = true;
    setStatus('Processing iris verification. Please wait…', 'info');
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
