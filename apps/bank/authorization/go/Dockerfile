FROM golang:1.24

WORKDIR /app

# Copy go mod and sum files
COPY go.mod go.sum ./

# Download dependencies
RUN go mod download

# Copy the source code
COPY . .

# Build the Go binary
RUN go build -o authorization

# Expose the port
EXPOSE 8080

# Run the application
CMD ["./authorization"]
