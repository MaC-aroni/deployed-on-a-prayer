// pm2 process list for the host laptop. deploy.sh starts this from the prod folder.
const path = require("path");

module.exports = {
  apps: [
    {
      name: "backend",
      cwd: path.join(__dirname, "backend"),
      script: path.join(__dirname, "backend/.venv/bin/uvicorn"),
      args: "app.main:app --host 0.0.0.0 --port 8000",
      interpreter: "none",
    },
    {
      name: "frontend",
      cwd: path.join(__dirname, "frontend"),
      script: path.join(__dirname, "frontend/node_modules/.bin/vite"),
      args: "preview --host 0.0.0.0 --port 3000 --strictPort",
      interpreter: "none",
    },
  ],
};
