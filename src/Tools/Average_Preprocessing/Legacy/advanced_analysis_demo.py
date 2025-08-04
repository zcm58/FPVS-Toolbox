# ruff: noqa
if __name__ == "__main__":
    root = ctk.CTk()


    class DummyMasterApp(ctk.CTk):
        def __init__(self):
            super().__init__()
            self.withdraw()
            self.validated_params = {
                "low_pass": 0.1, "high_pass": 50,
                "epoch_start": -1, "epoch_end": 2,
                "stim_channel": "Status"
            }
            self.save_folder_path = tk.StringVar(
                value=str(Path(os.getcwd()) / "test_adv_output_standalone")
            )
            try:
                os.makedirs(self.save_folder_path.get(), exist_ok=True)
            except Exception as e:
                logger.error("Error creating dummy output dir for test: %s", e)
            self.DEFAULT_STIM_CHANNEL = "Status"

        def log(self, message):
            logger.info("[DummyMasterLog] %s", message)

        def load_eeg_file(self, filepath):
            logger.info("DummyLoad: %s", filepath)
            return "dummy_raw_obj_for_test"

        def preprocess_raw(self, raw, **params):
            logger.info("DummyPreproc of '%s' with %s", raw, params)
            return "dummy_proc_raw_obj_for_test"


    try:
        dummy_master_app = DummyMasterApp()
        if run_advanced_averaging_processing is None:
            logger.critical(
                "CRITICAL ERROR: advanced_analysis_core.py (run_advanced_averaging_processing) could not be imported. Processing will fail.")

        advanced_window = AdvancedAnalysisWindow(master=dummy_master_app)
        dummy_master_app.mainloop()
    except Exception:
        logger.error("Error in __main__ of advanced_analysis.py: %s", traceback.format_exc())

