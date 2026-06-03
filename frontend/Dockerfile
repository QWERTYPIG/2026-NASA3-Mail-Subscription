# frontend/Dockerfile
FROM node:20-alpine

WORKDIR /app

# Copy package files and install dependencies
COPY package*.json .npmrc ./
RUN npm install

# Copy the rest of the frontend code
COPY . .

# Expose the standard dev port (3000 for Create React App)
EXPOSE 3000
