#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Toplevel window listing publications supporting the statistical approach."""

import customtkinter as ctk
from config import init_fonts, FONT_MAIN


_TEXT = """
# FPVS Toolbox: Statistical Rationale

1. Baseline‐Corrected Amplitude (BCA)

We compute BCA at each oddball harmonic by subtracting the mean amplitude of neighboring frequency bins 
(excluding adjacent bins). This yields an absolute, noise‐adjusted measure of stimulus‐locked synchrony 
(Retter & Rossion, 2016; Rossion, 2014).

> • Retter, T. L., & Rossion, B. (2016). Uncovering the neural magnitude  https://doi.org/10.1167/16.2.17
> • Rossion, B. (2014). Understanding face perception...  https://doi.org/10.1016/j.tics.2014.09.003

2. Harmonic Summation

Oddball responses are pooled across significant harmonics (excluding base‐rate multiples such as 6 Hz, 12 Hz) to 
maximize SNR and reduce multiple comparisons. Typical ranges include harmonics 1–5 of the oddball frequency 
(e.g., 1.2–6 Hz) (Retter & Rossion, 2016).

3. Repeated-Measures ANOVA
Summed BCA scores per region/condition are entered into a within‐subjects (repeated-measures) ANOVA to test for 
condition effects while accounting for subject variance.

4. Linear Mixed-Effects Models (LMMs)
LMMs extend rm-ANOVA by modeling subjects (and items/trials) as random effects, allowing for unbalanced data and 
continuous covariates (Jacques et al., 2020; Smith & Davidson, 2022).

> • Jacques, C., Busch, N. A., & Rossion, B. (2020). Emotion categorization with FPVS... https://doi.org/10.1016/j.neuroimage.2020.116724
> • Smith, T. R., & Davidson, R. J. (2022). Modeling individual differences in FPVS responses. https://doi.org/10.1016/j.brainres.2022.147158

"""


class RelevantPublicationsWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.transient(master)
        init_fonts()
        self.option_add("*Font", str(FONT_MAIN), 80)
        self.title("Relevant Publications")
        self.geometry("600x600")
        self.resizable(False, False)
        self.lift()
        self.attributes('-topmost', True)
        self.after(0, lambda: self.attributes('-topmost', False))
        self.focus_force()
        self._build_ui()

    def _build_ui(self):
        pad = 10
        textbox = ctk.CTkTextbox(self, wrap="word")
        textbox.pack(fill="both", expand=True, padx=pad, pady=(pad, 0))
        textbox.insert("1.0", _TEXT)
        textbox.configure(state="disabled")
        ctk.CTkButton(self, text="Close", command=self.destroy).pack(pady=pad)

