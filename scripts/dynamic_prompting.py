from __future__ import annotations
import sys
import logging
from string import Template
from pathlib import Path
import math

import gradio as gr

import modules.scripts as scripts
from modules.processing import process_images, fix_seed, Processed
from modules.shared import opts, OptionInfo
from modules.devices import get_optimal_device

from dynamicprompts.wildcardmanager import WildcardManager
from dynamicprompts.generators.promptgenerator import GeneratorException

from prompts.generator_builder import GeneratorBuilder
from prompts.uicreation import UiCreation
from ui import wildcards_tab, save_params, settings

VERSION = "2.4.1"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

is_debug = getattr(opts, "is_debug", False)

if is_debug:
    logger.setLevel(logging.DEBUG)

base_dir = Path(scripts.basedir())


def get_wildcard_manager():
    wildcard_dir = getattr(opts, "wildcard_dir", None)
    if wildcard_dir is None:
        wildcard_dir = base_dir / "wildcards"
    else:
        wildcard_dir = Path(wildcard_dir)

    wildcard_manager = WildcardManager(wildcard_dir)
    wildcard_manager.ensure_directory()

    return wildcard_manager


def get_prompts(p):
    original_prompt = p.all_prompts[0] if len(p.all_prompts) > 0 else p.prompt
    original_negative_prompt = (
        p.all_negative_prompts[0]
        if len(p.all_negative_prompts) > 0
        else p.negative_prompt
    )

    return original_prompt, original_negative_prompt

def get_seeds(p, num_seeds, use_fixed_seed):
    if use_fixed_seed:
        all_seeds = [p.seed] * num_seeds
    else:
        all_seeds = [
            int(p.seed) + (x if p.subseed_strength == 0 else 0)
            for x in range(num_seeds)
        ]

    return all_seeds

wildcard_manager = get_wildcard_manager()
wildcards_tab.initialize(wildcard_manager)
save_params.initialize()
settings.initialize()

device = 0 if get_optimal_device() == "cuda" else -1

MAGIC_PROMPT_MODELS = [
    "Gustavosta/MagicPrompt-Stable-Diffusion",
    "daspartho/prompt-extend",
    "succinctly/text2image-prompt-generator",
    "microsoft/Promptist",
    "AUTOMATIC/promptgen-lexart", 
    "AUTOMATIC/promptgen-majinai-safe", 
    "AUTOMATIC/promptgen-majinai-unsafe",
    "kmewhort/stable-diffusion-prompt-bolster",
    "Gustavosta/MagicPrompt-Dalle",
    "Ar4ikov/gpt2-650k-stable-diffusion-prompt-generator",
    "Ar4ikov/gpt2-medium-650k-stable-diffusion-prompt-generator",
    "crumb/bloom-560m-RLHF-SD2-prompter-aesthetic",
    "Meli/GPT2-Prompt",
    "DrishtiSharma/StableDiffusion-Prompt-Generator-GPT-Neo-125M"
]


def generate_prompts(
    prompt_generator, negative_prompt_generator, prompt, negative_prompt, num_prompts
):
    all_prompts = prompt_generator.generate(prompt, num_prompts)
    total_prompts = len(all_prompts)

    all_negative_prompts = negative_prompt_generator.generate(
        negative_prompt, num_prompts
    )

    if len(all_negative_prompts) < total_prompts:
        all_negative_prompts = all_negative_prompts * (
            total_prompts // len(all_negative_prompts) + 1
        )

    all_negative_prompts = all_negative_prompts[:total_prompts]

    return all_prompts, all_negative_prompts


class Script(scripts.Script):
    def title(self):
        return f"Dynamic Prompts v{VERSION}"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        ui_creation = UiCreation(wildcard_manager)
        wildcard_html = ui_creation.probe()

        html_path = base_dir / "helptext.html"
        html = html_path.open().read()
        html = Template(html).substitute(
            wildcard_html=wildcard_html,
            WILDCARD_DIR=wildcard_manager._path,
            VERSION=VERSION,
        )

        jinja_html_path = base_dir / "jinja_help.html"
        jinja_help = jinja_html_path.open().read()

        with gr.Group(elem_id="dynamic-prompting"):
            with gr.Accordion("Dynamic Prompts", open=False):
                is_enabled = gr.Checkbox(
                    label="Dynamic Prompts enabled",
                    value=True,
                    elem_id="dynamic-prompts-enabled",
                )

                with gr.Group():
                    is_combinatorial = gr.Checkbox(
                        label="Combinatorial generation",
                        value=False,
                        elem_id="is-combinatorial",
                    )

                    max_generations = gr.Slider(
                        label="Max generations (0 = all combinations - the batch count value is ignored)",
                        minimum=0,
                        maximum=1000,
                        step=1,
                        value=0,
                        elem_id="max-generations",
                    )

                    combinatorial_batches = gr.Slider(
                        label="Combinatorial batches",
                        minimum=1,
                        maximum=10,
                        step=1,
                        value=1,
                        elem_id="combinatorial-times",
                    )

                with gr.Accordion("Prompt Magic", open=False):
                    with gr.Group():
                        is_magic_prompt = gr.Checkbox(
                            label="Magic prompt", value=False, elem_id="is-magicprompt"
                        )

                        magic_prompt_length = gr.Slider(
                            label="Max magic prompt length",
                            value=100,
                            minimum=30,
                            maximum=300,
                            step=10,
                        )

                        magic_temp_value = gr.Slider(
                            label="Magic prompt creativity",
                            value=0.7,
                            minimum=0.1,
                            maximum=3.0,
                            step=0.10,
                        )

                        magic_model = gr.Dropdown(
                            MAGIC_PROMPT_MODELS,
                            value=MAGIC_PROMPT_MODELS[0], 
                            multiselect=False,
                            label="Magic prompt model",
                            elem_id="magic-prompt-model",
                        )

                    is_feeling_lucky = gr.Checkbox(
                        label="I'm feeling lucky",
                        value=False,
                        elem_id="is-feelinglucky",
                    )

                    with gr.Group():
                        is_attention_grabber = gr.Checkbox(
                            label="Attention grabber",
                            value=False,
                            elem_id="is-attention-grabber",
                        )

                        min_attention = gr.Slider(
                            label="Minimum attention",
                            value=1.1,
                            minimum=-1,
                            maximum=2,
                            step=0.1,
                        )

                        max_attention = gr.Slider(
                            label="Maximum attention",
                            value=1.5,
                            minimum=-1,
                            maximum=2,
                            step=0.1,
                        )

                    disable_negative_prompt = gr.Checkbox(
                        label="Don't apply to negative prompts",
                        value=True,
                        elem_id="disable-negative-prompt",
                    )

                with gr.Accordion("Need help?", open=False):
                    info = gr.HTML(html)

                enable_jinja_templates = False
                with gr.Group():
                    with gr.Accordion("Jinja2 templates", open=False):
                        enable_jinja_templates = gr.Checkbox(
                            label="Enable Jinja2 templates",
                            value=False,
                            elem_id="enable-jinja-templates",
                        )

                        with gr.Accordion("Help for Jinja2 templates", open=False):
                            jinja_info = gr.HTML(jinja_help)

                with gr.Group():
                    with gr.Accordion("Advanced options", open=False):
                        settings_info = gr.HTML(
                            "Some settings have been moved to the settings tab. Find them in the Dynamic Prompts section."
                        )

                        unlink_seed_from_prompt = gr.Checkbox(
                            label="Unlink seed from prompt",
                            value=False,
                            elem_id="unlink-seed-from-prompt",
                        )

                        use_fixed_seed = gr.Checkbox(
                            label="Fixed seed", value=False, elem_id="is-fixed-seed"
                        )

                        write_raw_template = gr.Checkbox(
                            label="Write raw prompt to image",
                            value=False,
                            visible=False,  # For some reason, removing this line causes Auto1111 to hang
                            elem_id="write-raw-template",
                        )

                        no_image_generation = gr.Checkbox(
                            label="Don't generate images",
                            value=False,
                            elem_id="no-image-generation",
                        )

                write_prompts = gr.Checkbox(
                    label="Write prompts to file",
                    value=False,
                    elem_id="write-prompts",
                    visible=False,  # For some reason, removing this line causes Auto1111 to hang
                )

        return [
            is_enabled,
            is_combinatorial,
            combinatorial_batches,
            is_magic_prompt,
            is_feeling_lucky,
            is_attention_grabber,
            min_attention,
            max_attention,
            magic_prompt_length,
            magic_temp_value,
            use_fixed_seed,
            unlink_seed_from_prompt,
            disable_negative_prompt,
            enable_jinja_templates,
            no_image_generation,
            max_generations,
            magic_model,
        ]

    def process(
        self,
        p,
        is_enabled,
        is_combinatorial,
        combinatorial_batches,
        is_magic_prompt,
        is_feeling_lucky,
        is_attention_grabber,
        min_attention,
        max_attention,
        magic_prompt_length,
        magic_temp_value,
        use_fixed_seed,
        unlink_seed_from_prompt,
        disable_negative_prompt,
        enable_jinja_templates,
        no_image_generation,
        max_generations,
        magic_model
    ):

        if not is_enabled:
            logger.debug("Dynamic prompts disabled - exiting")
            return p

        self._p = p

        ignore_whitespace = opts.dp_ignore_whitespace
        write_prompts = opts.dp_write_prompts_to_file

        fix_seed(p)

        original_prompt, original_negative_prompt = get_prompts(p)
        original_seed = p.seed
        num_images = p.n_iter * p.batch_size

        if is_combinatorial:
            if max_generations == 0:
                num_images = None
            else:
                num_images = max_generations
                
        combinatorial_batches = int(combinatorial_batches)

        try:
            logger.debug("Creating generator")
            generator_builder = (
                GeneratorBuilder(wildcard_manager, ignore_whitespace=ignore_whitespace)
                .set_is_feeling_lucky(is_feeling_lucky)
                .set_is_attention_grabber(
                    is_attention_grabber, min_attention, max_attention
                )
                .set_is_jinja_template(enable_jinja_templates)
                .set_is_combinatorial(is_combinatorial, combinatorial_batches)
                .set_is_magic_prompt(
                    is_magic_prompt, magic_model, magic_prompt_length, magic_temp_value
                )
                .set_is_dummy(False)
                .set_unlink_seed_from_prompt(unlink_seed_from_prompt)
                .set_seed(original_seed)
                .set_context(p)
            )

            generator = generator_builder.create_generator()

            if disable_negative_prompt:
                generator_builder.disable_prompt_magic()
                negative_generator = generator_builder.create_generator()
            else:
                negative_generator = generator

            all_prompts, all_negative_prompts = generate_prompts(
                generator,
                negative_generator,
                original_prompt,
                original_negative_prompt,
                num_images,
            )

        except GeneratorException as e:
            logger.exception(e)
            all_prompts = [str(e)]
            all_negative_prompts = [str(e)]

        updated_count = len(all_prompts)
        p.n_iter = math.ceil(updated_count / p.batch_size)

        all_seeds = get_seeds(p, updated_count, use_fixed_seed)

        logger.info(
            f"Prompt matrix will create {updated_count} images in a total of {p.n_iter} batches."
        )

        save_params.prompt_details.write_prompts = write_prompts
        save_params.prompt_details.original_prompt = original_prompt
        save_params.prompt_details.original_negative_prompt = original_negative_prompt
        save_params.prompt_details.all_prompts = all_prompts
        save_params.prompt_details.all_negative_prompts = all_negative_prompts

        p.all_prompts = all_prompts
        p.all_negative_prompts = all_negative_prompts
        if no_image_generation:
            logger.debug("No image generation requested - exiting")
            # Need a minimum of batch size images to avoid errors
            p.batch_size = 1
            p.all_prompts = all_prompts[0:1]

        p.all_seeds = all_seeds

        p.prompt_for_display = original_prompt

        p.prompt = original_prompt
        p.seed = original_seed
