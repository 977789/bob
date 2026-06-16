# Contributing to BLX

Thank you for your interest in contributing to BLX! This document provides guidelines and instructions for contributing to the project.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Testing](#testing)

## 📝 Code of Conduct

This project adheres to a code of conduct that promotes a welcoming and inclusive environment. By participating, you agree to:

- Be respectful and considerate
- Use welcoming and inclusive language
- Focus on what's best for the community
- Show empathy towards other community members

## 🚀 Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/your-username/BLX.git
   cd BLX
   ```
3. **Create a branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## 🤝 How to Contribute

### Reporting Bugs

Before creating bug reports, please check existing issues. When creating a bug report, include:

- **Clear title** describing the issue
- **Detailed description** of the problem
- **Steps to reproduce** the issue
- **Expected vs actual behavior**
- **Environment details** (OS, Python version, etc.)
- **Screenshots or logs** if applicable

### Suggesting Enhancements

Enhancement suggestions are welcome! Include:

- **Clear title** for the enhancement
- **Detailed description** of the proposed feature
- **Use cases** and benefits
- **Implementation suggestions** if you have any

### Code Contributions

1. **Check existing issues** for tasks to work on
2. **Comment on an issue** to express your interest
3. **Follow the development setup** below
4. **Make your changes** following coding standards
5. **Test thoroughly** before submitting
6. **Submit a pull request**

## 💻 Development Setup

### Prerequisites

- Python 3.8 or higher
- Git
- Docker (optional but recommended)

### Local Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up configuration:**
   ```bash
   cp config_sample.py config.py
   # Edit config.py with your test bot credentials
   ```

3. **Run tests:**
   ```bash
   python -m pytest tests/
   ```

4. **Start the bot (for testing):**
   ```bash
   python -m bot
   ```

### Docker Setup

```bash
docker-compose up --build
```

## 🔄 Pull Request Process

### Before Submitting

- [ ] Code follows project coding standards
- [ ] Tests pass locally
- [ ] Documentation updated if needed
- [ ] Commit messages are clear and descriptive
- [ ] Branch is up to date with main

### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Tests pass
- [ ] Manual testing completed

## Additional Notes
Any additional context or notes
```

### Review Process

1. **Automated checks** must pass
2. **Code review** by maintainers
3. **Discussion** and iterations if needed
4. **Merge** once approved

## 📏 Coding Standards

### Python Style

- **Follow PEP 8** style guidelines
- **Use meaningful names** for variables and functions
- **Add docstrings** for functions and classes
- **Keep functions small** and focused
- **Use type hints** where appropriate

### Example:

```python
def download_file(url: str, destination: str) -> bool:
    """
    Download a file from URL to destination.
    
    Args:
        url: The URL to download from
        destination: Local path to save the file
        
    Returns:
        True if successful, False otherwise
    """
    # Implementation here
    pass
```

### File Organization

- **Group related functions** in modules
- **Use clear directory structure**
- **Import organization**: stdlib, third-party, local imports
- **Avoid circular imports**

### Writing Tests

- **Test new features** and bug fixes
- **Use descriptive test names**
- **Include edge cases**
- **Mock external dependencies**

### Test Structure

```python
import pytest
from bot.module import function_to_test

class TestFeatureName:
    def test_normal_case(self):
        result = function_to_test("input")
        assert result == "expected_output"
        
    def test_edge_case(self):
        with pytest.raises(ValueError):
            function_to_test(None)
```

## 📚 Documentation

When contributing:

- **Update relevant documentation**
- **Add docstrings** for new functions
- **Update README** if needed
- **Create feature documentation** for new features

## ❓ Getting Help

If you need help:

- **Check existing issues** and documentation
- **Ask in discussions** for general questions
- **Create an issue** for specific problems
- **Join our community channels** (if available)

## 🎉 Recognition

Contributors will be:

- **Listed in contributors** section
- **Mentioned in release notes** for significant contributions
- **Credited appropriately** in code comments

---

Thank you for contributing to BLX! Your contributions make this project better for everyone. 🚀
