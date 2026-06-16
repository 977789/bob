# BLX - Advanced Mirror & Leech Telegram Bot

<div align="center">
    <img width="300" src="assets/BHARTIYEE LEECH.png" alt="BLX Logo">
    
**A powerful, feature-rich Telegram bot for mirroring and leeching files with enhanced functionality and professional deployment options.**

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Supported-blue?logo=docker&logoColor=white)](https://www.docker.com/)
[![License](https://img.shields.io/github/license/bhartiyeeleech/BLX?color=green)](LICENSE)
[![Issues](https://img.shields.io/github/issues/bhartiyeeleech/BLX)](https://github.com/bhartiyeeleech/BLX/issues)

</div>

## ✨ Features

- **Mirror & Leech**: Support for torrents, magnet links, and direct downloads
- **Media Processing**: Advanced metadata editing for audio/video files
- **Sequential Processing**: Queue-based download management
- **Auto Resume**: Intelligent resume for incomplete downloads
- **User Management**: Advanced user session and permission controls
- **Multiple Protocols**: Support for HTTP, FTP, Mega, Google Drive, and more
- **Watermark Support**: Add custom watermarks to media files
- **Professional UI**: Clean web interface for monitoring and control

## 🚀 Quick Start

### Using Docker (Recommended)

1. Clone the repository:
```bash
git clone https://github.com/bhartiyeeleech/BLX.git
cd BLX
```

2. Configure your bot:
```bash
cp config_sample.py config.py
# Edit config.py with your settings
```

3. Run with Docker Compose:
```bash
docker-compose up -d
```

### Manual Installation

1. Clone and navigate:
```bash
git clone https://github.com/bhartiyeeleech/BLX.git
cd BLX
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure and run:
```bash
cp config_sample.py config.py
# Edit config.py
python -m bot
```

## 📖 Documentation

- [**Configuration Guide**](docs/configuration.md) - Bot setup and configuration
- [**Feature Documentation**](docs/) - Detailed feature explanations
- [**Deployment Guide**](docs/deployment.md) - Various deployment methods
- [**API Reference**](docs/api.md) - API documentation

## 🛠️ Configuration

Key configuration options in `config.py`:

```python
# Bot Token (required)
BOT_TOKEN = "your_bot_token_here"

# Owner/Admin settings
OWNER_ID = your_telegram_user_id

# Download settings
DOWNLOAD_DIR = "/usr/src/app/downloads/"
MAX_SPLIT_SIZE = 2097152000  # 2GB

# Media processing
METADATA_ENABLED = True
WATERMARK_ENABLED = True
```

## 🧪 Testing

Run the test suite:

```bash
# Run all tests
python -m pytest tests/

# Run specific test
python -m pytest tests/test_sequential_processor.py
```

## 📋 Requirements

- Python 3.8 or higher
- Telegram Bot API token
- Sufficient storage space for downloads
- (Optional) Google Drive API credentials for cloud storage

## 🤝 Contributing

We welcome contributions! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Based on the [mirror-leech-telegram-bot](https://github.com/anasty17/mirror-leech-telegram-bot) project
- Enhanced with features from the [WZML-X](https://github.com/weebzone/WZML-X) fork
- Special thanks to all contributors and the open-source community

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/bhartiyeeleech/BLX/issues)
- **Discussions**: [GitHub Discussions](https://github.com/bhartiyeeleech/BLX/discussions)

---

<div align="center">
    <strong>⭐ Star this repository if you find it useful!</strong>
</div>
