# Trading Framework

A Python framework for forex trading, backtesting, and strategy development.

---

## 📦 Initial System Set-up

### 1. Install Homebrew
[Homebrew](https://brew.sh/) is a package manager for macOS that makes it easy to install and update software from the command line.

1. Download and install Homebrew from the official website:  
👉 [https://brew.sh/](https://brew.sh/)


2. When you install Homebrew, you'll be asked to paste a command into your terminal. Copy it exactly as shown on the website and press **Enter**.  


3. After installation, open **Terminal** and run:

```bash
brew --version
```

If installed correctly, this will display the version number of Homebrew.

### 2. Install Anaconda via Homebrew
1. Use Homebrew to install Anaconda:

```bash
brew install --cask anaconda
```

2. Initialize Anaconda

After installation, initialize conda with:

```bash
conda init "$(basename "${SHELL}")"
```

3. Verify Anaconda

Restart your terminal, then check:

```bash
conda --version
```

### 3. Install VS Code
1. Use Homebrew to install VS Code:

```bash
brew install --cask visual-studio-code
```

2. Launch VS Code from the terminal:
```bash
code
```

#### Install Python Extension for VS Code
1. Open VS Code.  
2. Go to the Extensions Marketplace (`Ctrl+Shift+X` or `Cmd+Shift+X` on macOS).  
3. Search for **Python** and install the official extension by Microsoft.  

---

### 4. Set up an Anaconda Environment sds
Open a terminal and create a dedicated environment for this project:

```bash
conda create -n trading-env python=3.9
conda activate trading-env
```

### 5. Connect Anaconda Environment to VS Code

In VS Code, press Ctrl+Shift+P (Cmd+Shift+P on macOS).

Search for Python: Select Interpreter.

Choose the interpreter corresponding to your Anaconda environment
(e.g. Python 3.9 (trading-env)).

### 6. Git & SourceTree

You can manage this project with [SourceTree](https://www.sourcetreeapp.com/), a Git GUI client.

#### 6.1 Install SourceTree (via Homebrew)
Use Homebrew to install SourceTree:

```bash
brew install --cask sourcetree
```

#### 6.2 Find Your Repository on Bitbucket
1. Navigate to your repository in Bitbucket:  
   👉 [https://bitbucket.org/trading-max/trading_v2](https://bitbucket.org/trading-max/trading_v2)  
2. Click the **Clone** button (top right).  
3. Copy the HTTPS URL:  
```bash
 https://MaxCarrington@bitbucket.org/trading-max/trading_v2.git
 ```

#### 6.3 Clone the Repository in SourceTree

Open SourceTree.

Click Clone (top left).

Paste the repository URL into the Source URL field.

Choose a destination folder (e.g. ~/Repo's/trading_v2).

Click Clone to download the repo.

### 7. Install Project Dependencies

1. After cloning the repository, open a terminal and navigate into the cloned project folder:

```bash
cd ~/Projects/trading_v2
```

2. All required libraries are listed in pyproject.toml.
Install them with:

```bash
pip install -e .[dev]
```

-e . installs the project in editable mode, so changes in src/ are picked up immediately.

[dev] also installs extra developer tools (linting, formatting, testing).

## 📂 Project Structure

```text
your-project/
├─ pyproject.toml            # or requirements.txt + setup.cfg
├─ README.md
├─ .gitignore
├─ .pre-commit-config.yaml   # optional but recommended
├─ env/                      # (optional) local venv; usually gitignored
├─ configs/                  # YAML/TOML configs for runs
│   ├─ backtest.yaml
│   └─ live.yaml
├─ src/
│   └─ trading/              # import as `import trading`
│       ├─ __init__.py
│       ├─ data/             # data I/O, APIs, caching
│       │   ├─ loaders.py
│       │   └─ store.py
│       ├─ indicators/       # TA utilities
│       │   ├─ rsi.py
│       │   └─ bollinger.py
│       ├─ strategies/       # strategy definitions
│       │   ├─ mean_reversion.py
│       │   └─ momentum.py
│       ├─ backtesting/      # engine, metrics
│       │   ├─ engine.py
│       │   └─ metrics.py
│       ├─ execution/        # broker/ccxt wrappers, live trading
│       │   └─ broker.py
│       ├─ plotting/         # chart utilities
│       │   └─ charts.py
│       └─ utils/            # common helpers (config, logging, time)
│           ├─ config.py
│           └─ logging.py
├─ tests/                    # mirrors src/ (pytest)
│   └─ test_mean_reversion.py
├─ notebooks/                # exploratory work only
│   └─ 2025-09-10-eda.ipynb
├─ scripts/                  # CLI entry points / runnable scripts
│   ├─ fetch_data.py
│   ├─ run_backtest.py
│   └─ run_live.py
├─ data/                     # gitignored
│   ├─ raw/
│   ├─ interim/
│   └─ processed/
├─ reports/
│   ├─ figures/              # charts/plots (gitignore if large)
│   └─ backtests/            # HTML/CSV summaries (often gitignored)
├─ logs/                     # gitignored
└─ docs/                     # documentation/diagrams
```