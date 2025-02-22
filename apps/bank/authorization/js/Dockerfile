# Use an official Node.js runtime as a parent image.
FROM node:18-alpine

# Set the working directory inside the container.
WORKDIR /app

# Copy package.json and package-lock.json (if present) to leverage Docker cache.
COPY package*.json ./

# Install Node.js dependencies.
RUN npm install

# Copy the rest of the application code.
COPY . .

# Expose the port that your service listens on.
EXPOSE 8080

# Command to run your Node.js service.
CMD ["node", "authorization.js"]
