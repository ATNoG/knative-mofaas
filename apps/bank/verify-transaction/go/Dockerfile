FROM golang:1.24-alpine

WORKDIR /app

# Copy go mod and sum files
COPY go.mod go.sum ./

# Download dependencies
RUN go mod download

# Copy the source code
COPY . .

# Build the Go binary
RUN go build -o verify_transaction

# Expose the port
EXPOSE 8080

# Run the application
CMD ["./verify_transaction"]
