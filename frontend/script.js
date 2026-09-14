const startButton = document.getElementById("startButton");
const demoButton = document.getElementById("demoButton");

function launchExperience() {
  document.getElementById("how-it-works").scrollIntoView({ behavior: "smooth" });
}

startButton?.addEventListener("click", launchExperience);
demoButton?.addEventListener("click", launchExperience);
