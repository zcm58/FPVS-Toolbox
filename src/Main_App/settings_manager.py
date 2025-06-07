import os
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
        'stats_size': '950x950',
        'resizer_size': '800x600',
        'advanced_size': '1050x850'
    },
    'stim': {
        'channel': 'Status'
    },
    'events': {
        'labels': '',
        'ids': ''
    }
}

INI_NAME = 'settings.ini'

class SettingsManager:
    """Handles loading and saving user preferences to an INI file."""

    def __init__(self, ini_path: str = None):
        if ini_path is None:
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ini_path = os.path.join(repo_root, INI_NAME)
        self.ini_path = ini_path
        self.config = configparser.ConfigParser()
        self.load()

    def load(self) -> None:
        """Load settings from disk, applying defaults where needed."""
        self.config.read_dict(DEFAULTS)
        if os.path.exists(self.ini_path):
            self.config.read(self.ini_path)

    def save(self) -> None:
        """Write the current settings to disk."""
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
        labels = [l.strip() for l in self.get('events', 'labels', '').split(',') if l.strip()]
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
