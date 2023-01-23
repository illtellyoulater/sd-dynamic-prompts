from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path

from modules import script_callbacks
from modules.script_callbacks import ImageSaveParams
from modules.shared import opts

from prompts import prompt_writer


@dataclass
class PromptDetails:
    write_prompts: bool = False
    original_prompt: str = ""
    original_negative_prompt: str = ""
    all_prompts: list[str] = field(default_factory=list)
    all_negative_prompts: list[str] = field(default_factory=list)
    already_saved: bool = False


logger = logging.getLogger(__name__)

prompt_details = PromptDetails()


def write_prompts(filename: str, prompt_details: PromptDetails):
    prompt_filename = Path(filename).with_suffix(".csv")
    if prompt_details.write_prompts and not prompt_details.already_saved:
        prompt_writer.write_prompts(
            prompt_filename,
            prompt_details.original_prompt,
            prompt_details.original_negative_prompt,
            prompt_details.all_prompts,
            prompt_details.all_negative_prompts,
        )

        prompt_details.already_saved = True


def on_before_image_saved(image_save_params: ImageSaveParams):
    try:
        write_prompts(image_save_params.filename, prompt_details)
        save_metadata = opts.dp_write_raw_template
        if save_metadata:
            if image_save_params.p.prompt != "":
                image_save_params.pnginfo["parameters"] += (
                    "\nTemplate:" + image_save_params.p.prompt
                )

            if image_save_params.p.negative_prompt != "":
                image_save_params.pnginfo["parameters"] += (
                    "\nNegative Template:" + image_save_params.p.negative_prompt
                )
    except Exception as e:
        logger.exception("Error save metadata to image")


def initialize():
    script_callbacks.on_before_image_saved(on_before_image_saved)
