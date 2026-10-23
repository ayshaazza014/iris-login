// 1. Find things on the page using their name tags
const video = document.getElementById("camera");
const button = document.getElementById("startBtn");
const message = document.getElementById("message");

// 2. When the button is clicked, run this function
button.addEventListener("click", startCamera);

async function startCamera() {
  try {
    // 3. Ask the browser for the camera
    const stream = await navigator.mediaDevices.getUserMedia({ video: true });

    // 4. Connect the camera to the TV screen
    video.srcObject = stream;

    message.textContent = "Camera is ON. Look at the camera.";
  } catch (error) {
    // 5. If something goes wrong
    message.textContent = "Camera not allowed or not found.";
    console.log(error);
  }
}