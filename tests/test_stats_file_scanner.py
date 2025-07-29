import importlib.util
import os


def _import_scanner_module():
    path = os.path.join(
        os.path.dirname(__file__),
        '..',
        'src',
        'Tools',
        'Stats',
        'Legacy',
        'stats_file_scanner.py',
    )
    spec = importlib.util.spec_from_file_location('stats_file_scanner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stats_file_scanner = _import_scanner_module()


class DummyVar:
    def __init__(self, value=""):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class DummyStats:
    def __init__(self, folder):
        self.stats_data_folder_var = DummyVar(folder)
        self.detected_info_var = DummyVar()
        self.condition_A_var = DummyVar()
        self.condition_B_var = DummyVar()
        self.subject_data = {}
        self.subjects = []
        self.conditions = []
        self.all_subject_data = {}
        self.rm_anova_results_data = None
        self.harmonic_check_results_data = []
        self.condA_menu = None
        self.condB_menu = None
        self.logs = []

    def log_to_main_app(self, msg):
        self.logs.append(msg)


DummyStats.scan_folder = stats_file_scanner.scan_folder
DummyStats.update_condition_menus = stats_file_scanner.update_condition_menus
DummyStats.update_condition_B_options = stats_file_scanner.update_condition_B_options


def test_scan_folder_ignores_default_dirs(tmp_path):
    cond1 = tmp_path / "CondA"
    cond1.mkdir()
    cond2 = tmp_path / "CondB"
    cond2.mkdir()
    ignore1 = tmp_path / ".FIF FILES"
    ignore1.mkdir()
    ignore2 = tmp_path / "LoReTA RESULTS"
    ignore2.mkdir()

    for folder in [cond1, cond2, ignore1, ignore2]:
        with open(folder / "P01_data.xlsx", "w") as f:
            f.write("test")

    dummy = DummyStats(str(tmp_path))
    dummy.scan_folder()

    assert set(dummy.conditions) == {"CondA", "CondB"}
