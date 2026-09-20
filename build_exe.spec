# PyInstaller 打包配置：UOM 适飞空域查询（桌面版）
# 用法: pyinstaller build_exe.spec --noconfirm
#
# 打成一个单文件 exe。数据文件约 90MB，压缩后单文件在 60~80MB 量级。
# --onefile 启动时会先解压到临时目录，首次启动稍慢（1~3 秒）。

block_cipher = None

datas = [
    ('index.html', '.'),
    ('tile-worker.js', '.'),
    ('serve.py', '.'),
    ('pmtiles_tool.py', '.'),
    ('lib', 'lib'),
    ('data', 'data'),
]

hiddenimports = [
    'webview',
    'webview.platforms.edgechromium',
    'clr_loader',
    'pythonnet',
]

a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 本机 site-packages 里装了大量无关的大库（torch/sklearn/opencv 等），
    # 不排除的话单文件会到 360MB+。实测排除后降到 90MB 量级。
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'scipy', 'pandas',
        'PyQt5', 'PySide2', 'PySide6', 'IPython', 'pytest',
        'torch', 'torchvision', 'torchaudio', 'sklearn', 'cv2',
        'transformers', 'datasets', 'accelerate', 'sentencepiece',
        'onnx', 'onnxruntime', 'tensorflow', 'keras', 'jax',
        'sympy', 'networkx', 'lxml', 'sqlalchemy', 'babel',
        'notebook', 'jupyter', 'jupyterlab', 'nbconvert',
        'IPython.display', 'pytest_asyncio', 'sphinx',
        'google', 'grpc', 'protobuf', 'h5py', 'numba',
        'pynvml', 'nvidia', 'triton', 'xgboost', 'lightgbm',
        'plotly', 'dash', 'streamlit', 'gradio',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='UOM适飞空域查询',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
