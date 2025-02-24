FROM php:8.2-cli

# Install required dependencies
RUN apt-get update && apt-get install -y \
    libcurl4-openssl-dev \
    libbrotli-dev \
    unzip zip git zlib1g-dev \
    && pecl install swoole \
    && docker-php-ext-enable swoole \
    && curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application files
COPY . /app

# Install dependencies
RUN composer install --no-dev --optimize-autoloader

# Expose port 8080
EXPOSE 8080

# Start the application
CMD ["php", "verify_transaction.php"]
