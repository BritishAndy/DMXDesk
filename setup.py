"""
py2app build script for DMX Desk Emulator
Run with: python3 setup.py py2app
"""
from setuptools import setup

APP = ['desk.py']

DATA_FILES = [
    # Include the fixtures folder and any JSON files in the app bundle
    ('fixtures', ['fixtures/' + f for f in __import__('os').listdir('fixtures')
                  if f.endswith('.json')]),
]

OPTIONS = {
    'argv_emulation': False,        # Must be False for Tkinter apps on macOS
    'iconfile': 'icon.icns',        # App icon (generated separately)
    'plist': {
        'CFBundleName':             'DMX Desk',
        'CFBundleDisplayName':      'DMX Desk',
        'CFBundleIdentifier':       'com.yourname.dmxdesk',
        'CFBundleVersion':          '1.0.0',
        'CFBundleShortVersionString': '1.0',
        'NSHumanReadableCopyright': '© 2026',
        'LSMinimumSystemVersion':   '10.14.0',
        'NSHighResolutionCapable':  True,
        # Allow network access for Art-Net
        'NSAppTransportSecurity': {
            'NSAllowsArbitraryLoads': True,
        },
    },
    'packages': [],
    'includes': [
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.colorchooser',
        'tkinter.filedialog',
        'json',
        'pathlib',
        'socket',
        'threading',
        'urllib.request',
        'urllib.error',
        'urllib.parse',
        'datetime',
        'subprocess',
        'time',
        'argparse',
    ],
    'excludes': [
        'numpy', 'scipy', 'matplotlib', 'PIL', 'wx',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'setuptools', 'pip',
    ],
    # Copy patch files and prefs alongside the app
    'resources': [],
}

setup(
    name='DMX Desk',
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
