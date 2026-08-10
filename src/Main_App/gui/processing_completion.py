"""Current-app processing completion state and user feedback."""

from __future__ import annotations

import gc

import pandas as pd

from Main_App.Shared import user_messages


def finalize_processing_host_state(host, success: bool) -> None:
    """Show completion feedback and reset host state after processing."""

    cancelled = bool(getattr(host, "_suppress_completion_dialogs", False))
    if cancelled and not success:
        host.log("--- Processing Run Cancelled by User ---")
        return

    if success:
        host.log("--- Processing Run Completed Successfully ---")
        if host.validated_params and host.data_paths:
            output_folder = host.save_folder_path.get()
            file_count = len(host.data_paths)
            user_messages.show_info(
                "Processing Complete",
                (
                    f"Analysis finished for {file_count} "
                    f"file{'s' if file_count != 1 else ''}.\n"
                    f"Excel files saved to:\n{output_folder}"
                ),
                host,
            )
        else:
            user_messages.show_info(
                "Processing Finished",
                "Processing run finished. Check logs for details.",
                host,
            )
    else:
        host.log("--- Processing Run Finished with ERRORS ---")
        user_messages.show_error(
            "Processing Error",
            "An error occurred during processing. Please check the log for details.",
            host,
        )

    host.busy = False
    host._set_controls_enabled(True)
    host.log(f"--- GUI Controls Re-enabled at {pd.Timestamp.now()} ---")

    host.data_paths = []
    host._max_progress = 1
    host.progress_bar.set(0.0)
    host._current_progress = 0.0
    host._target_progress = 0.0
    host._start_time = None
    host._processed_count = 0
    if hasattr(host, "remaining_time_var") and host.remaining_time_var is not None:
        host.remaining_time_var.set("")
    host.preprocessed_data = {}

    log_text = getattr(host, "log_text", None)
    winfo_exists = getattr(log_text, "winfo_exists", None)
    if callable(winfo_exists) and winfo_exists():
        log_text.configure(state="normal")
        ready_msg = (
            f"{pd.Timestamp.now().strftime('%H:%M:%S.%f')[:-3]} [GUI]: "
            "Ready for next file selection...\n"
        )
        log_text.insert("end", ready_msg)
        log_text.see("end")
        log_text.configure(state="disabled")

    host.processing_thread = None
    host._queue_job_id = None
    gc.collect()
    host.log("--- State Reset. Ready for next run. ---")


__all__ = ["finalize_processing_host_state"]
