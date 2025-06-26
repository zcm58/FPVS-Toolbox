"""Utilities for storing and retrieving user preferences.

This module defines :class:`SettingsManager` which reads and writes an INI file
containing GUI options, analysis defaults and other persistent settings.  It
also provides helpers for manipulating event label/ID pairs and detecting debug
mode.
"""

import os
import sys
import configparser
from typing import List, Tuple

DEFAULTS = {
    'appearance': {
        'mode': 'System',
        'theme': 'blue'
    },
    'paths': {
        'data_folder': '',
        'output_folder': ''
    },
    'gui': {
        'main_size': '750x920',
        'stats_size': '700x650',
        'resizer_size': '600x600',
        'advanced_size': '500x500'
    },
    'stim': {
        'channel': 'Status'
    },
    'events': {
        'labels': '',
        'ids': ''
    },
    'analysis': {
        'base_freq': '6.0',
        'oddball_freq': '1.2',
        'bca_upper_limit': '16.8',
        'alpha': '0.05'
    },
    'rois': {
        'names': 'Frontal Lobe;Central Lobe;Parietal Lobe;Occipital Lobe',
        'electrodes': 'F3,F4,Fz;C3,C4,Cz;P3,P4,Pz;O1,O2,Oz'
    },
    'loreta': {
        'mri_path': '',
        'loreta_low_freq': '0.1',
        'loreta_high_freq': '40.0',
        'loreta_threshold': '0.0',
        'oddball_harmonics': '1,2,3',
        'loreta_snr': '3.0',
        'auto_oddball_localization': 'False',
        'baseline_tmin': '-0.2',
        'baseline_tmax': '0.0',
        'time_window_start_ms': '',
        'time_window_end_ms': ''
    },
    'debug': {
        'enabled': 'False'
    }
}

INI_NAME = 'settings.ini'

def _default_ini_path() -> str:
    """Return the default path for the settings file in a user-writable location."""
    if sys.platform.startswith('win'):
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    else:
        base = os.environ.get('XDG_CONFIG_HOME', os.path.join(os.path.expanduser('~'), '.config'))
    return os.path.join(base, 'FPVS_Toolbox', INI_NAME)

class SettingsManager:
    """Handles loading and saving user preferences to an INI file."""

    def __init__(self, ini_path: str = None):
        if ini_path is None:
            ini_path = _default_ini_path()
        self.ini_path = ini_path
        self.config = configparser.ConfigParser()
        self.load()

    def load(self) -> None:
        """Load settings from disk, applying defaults where needed."""
        self.config.read_dict(DEFAULTS)
        missing_loreta = False
        if os.path.exists(self.ini_path):
            existing = configparser.ConfigParser()
            existing.read(self.ini_path)
            if not existing.has_section('loreta') or not existing.has_option('loreta', 'mri_path'):
                missing_loreta = True
            for opt in (
                'loreta_low_freq',
                'loreta_high_freq',
                'loreta_threshold',
                'oddball_harmonics',
                'loreta_snr',
                'auto_oddball_localization',
                'baseline_tmin',
                'baseline_tmax',
                'time_window_start_ms',
                'time_window_end_ms',
            ):
                if not existing.has_option('loreta', opt):
                    missing_loreta = True
            self.config.read(self.ini_path)
        if missing_loreta:
            self.save()

    def save(self) -> None:
        """Write the current settings to disk."""
        os.makedirs(os.path.dirname(self.ini_path), exist_ok=True)
        with open(self.ini_path, 'w') as f:
            self.config.write(f)

    def reset(self) -> None:
        """Reset settings to defaults and save."""
        self.config.read_dict(DEFAULTS)
        self.save()

    def get(self, section: str, option: str, fallback: str = '') -> str:
        return self.config.get(section, option, fallback=fallback)

    def set(self, section: str, option: str, value: str) -> None:
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, option, value)

    # --- Convenience helpers for event mappings ---
    def get_event_pairs(self) -> List[Tuple[str, str]]:
        labels = [label_part.strip() for label_part in self.get('events', 'labels', '').split(',') if label_part.strip()]
        ids = [i.strip() for i in self.get('events', 'ids', '').split(',') if i.strip()]
        pairs = []
        for label, id_val in zip(labels, ids):
            pairs.append((label, id_val))
        return pairs

    def set_event_pairs(self, pairs: List[Tuple[str, str]]) -> None:
        labels = ','.join([p[0] for p in pairs])
        ids = ','.join([p[1] for p in pairs])
        self.set('events', 'labels', labels)
        self.set('events', 'ids', ids)

    # --- Convenience helpers for ROI mappings ---
    def get_roi_pairs(self) -> List[Tuple[str, List[str]]]:
        names = [n.strip() for n in self.get('rois', 'names', '').split(';') if n.strip()]
        groups = [g.strip() for g in self.get('rois', 'electrodes', '').split(';') if g.strip()]
        pairs = []
        for name, group in zip(names, groups):
            electrodes = [e.strip().upper() for e in group.split(',') if e.strip()]
            pairs.append((name, electrodes))
        return pairs

    def set_roi_pairs(self, pairs: List[Tuple[str, List[str]]]) -> None:
        names = ';'.join([p[0] for p in pairs])
        electrodes = ';'.join([','.join([e.upper() for e in p[1]]) for p in pairs])
        self.set('rois', 'names', names)
        self.set('rois', 'electrodes', electrodes)

    def debug_enabled(self) -> bool:
        return self.get('debug', 'enabled', 'False').lower() == 'true'
