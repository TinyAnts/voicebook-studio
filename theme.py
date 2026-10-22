"""Warm charcoal theme. Both system modes use the same readable dark palette."""
import gradio as gr
from gradio.themes import colors

ACCENT = colors.Color(name='terracotta', c50='#fff6f0', c100='#fbe5d8', c200='#f2c9b3',
                      c300='#eab298', c400='#e3a187', c500='#d99a7d', c600='#ba765d',
                      c700='#925942', c800='#674332', c900='#423028', c950='#2b211c')
NEUTRAL = colors.Color(name='warmstone', c50='#faf8f2', c100='#f2efe8', c200='#ddd7cd',
                       c300='#c8c1b7', c400='#b5ada1', c500='#938b7f', c600='#706a60',
                       c700='#555149', c800='#3e3b35', c900='#30302c', c950='#222221')


def make_theme():
    theme = gr.themes.Base(primary_hue=ACCENT, secondary_hue=ACCENT, neutral_hue=NEUTRAL,
                           font=['Segoe UI', 'Arial', 'sans-serif'],
                           font_mono=['Consolas', 'Liberation Mono', 'monospace'])
    # Set BOTH variants: an OS/browser mode change must never pair dark text with
    # the dark background. Do not rely on inherited Gradio light-mode colours.
    paired = dict(
        body_background_fill='#262624', body_text_color='#f2efe8', body_text_color_subdued='#c8c1b7',
        background_fill_primary='#30302c', background_fill_secondary='#35342f',
        border_color_primary='#625d54', border_color_accent='#e3a187', border_color_accent_subdued='#82766b',
        color_accent_soft='#46372f', link_text_color='#efb89a', link_text_color_hover='#ffd4ba',
        link_text_color_active='#ffd4ba', link_text_color_visited='#efb89a',
        block_background_fill='#30302c', block_border_color='#555149', block_border_width='1px',
        block_info_text_color='#c8c1b7', block_label_background_fill='transparent',
        block_label_border_color='transparent', block_label_border_width='0px', block_label_text_color='#eee9df',
        block_title_background_fill='transparent', block_title_border_color='transparent',
        block_title_border_width='0px', block_title_text_color='#f2efe8', block_shadow='none',
        panel_background_fill='#30302c', panel_border_color='#555149', panel_border_width='1px',
        accordion_text_color='#eee9df', table_text_color='#eee9df',
        input_background_fill='#232321', input_background_fill_focus='#292823', input_background_fill_hover='#292823',
        input_border_color='#82796d', input_border_color_focus='#e3a187', input_border_color_hover='#b5ada1',
        input_border_width='1px', input_placeholder_color='#b5ada1', input_shadow='none',
        input_shadow_focus='0 0 0 2px #e3a18755',
        checkbox_background_color='#232321', checkbox_background_color_hover='#3e3b35',
        checkbox_background_color_focus='#3e3b35', checkbox_background_color_selected='#d99a7d',
        checkbox_border_color='#a69b8c', checkbox_border_color_hover='#e3a187',
        checkbox_border_color_focus='#e3a187', checkbox_border_color_selected='#d99a7d', checkbox_border_width='1px',
        checkbox_label_background_fill='#232321', checkbox_label_background_fill_hover='#3e3b35',
        checkbox_label_background_fill_selected='#49382f', checkbox_label_border_color='#82796d',
        checkbox_label_border_color_hover='#b5ada1', checkbox_label_border_color_selected='#e3a187',
        checkbox_label_border_width='1px', checkbox_label_text_color='#eee9df', checkbox_label_text_color_selected='#fff0e6',
        error_background_fill='#44302e', error_border_color='#c68f85', error_text_color='#ffd1c9', error_icon_color='#ffd1c9',
        loader_color='#e3a187', slider_color='#e3a187', stat_background_fill='#35342f',
        table_border_color='#625d54', table_even_background_fill='#30302c', table_odd_background_fill='#35342f', table_row_focus='#46372f',
        button_primary_background_fill='#d99a7d', button_primary_background_fill_hover='#eab298',
        button_primary_border_color='#d99a7d', button_primary_border_color_hover='#eab298',
        button_primary_text_color='#261e1a', button_primary_text_color_hover='#261e1a',
        button_secondary_background_fill='#3b3933', button_secondary_background_fill_hover='#4a463e',
        button_secondary_border_color='#82796d', button_secondary_border_color_hover='#b5ada1',
        button_secondary_text_color='#f2efe8', button_secondary_text_color_hover='#fff8ee',
        button_cancel_background_fill='#49312f', button_cancel_background_fill_hover='#5a3a35',
        button_cancel_border_color='#c68f85', button_cancel_border_color_hover='#e6aba0',
        button_cancel_text_color='#ffd1c9', button_cancel_text_color_hover='#ffe3dd',
        button_border_width='1px', code_background_fill='#222221',
    )
    settings = {key: value for name, value in paired.items() for key in (name, name+'_dark')}
    settings.update(color_accent='#e3a187', body_text_size='15px', prose_text_size='15px',
                    block_info_text_size='13px', block_label_text_size='13px', block_label_text_weight='600',
                    block_label_padding='0 0 8px', block_label_margin='0', block_label_radius='0',
                    block_label_right_radius='0', block_label_shadow='none', checkbox_label_shadow='none', block_padding='16px',
                    block_radius='12px', container_radius='12px', input_radius='8px', input_text_size='14px',
                    button_large_radius='9px', button_small_radius='8px', button_medium_radius='8px',
                    button_large_text_size='15px', button_small_text_size='13px', button_medium_text_size='14px',
                    button_large_text_weight='650', button_medium_text_weight='600',
                    section_header_text_size='17px', section_header_text_weight='600',
                    layout_gap='16px', form_gap_width='1px', checkbox_label_gap='8px',
                    button_transform_hover='none', button_transform_active='none')
    return theme.set(**settings)


THEME = make_theme()

CSS = '''
:root, body, .gradio-container {color-scheme:dark;}
body {background:#262624;}
.gradio-container {
  width:100%!important;min-width:0!important;max-width:1240px!important;box-sizing:border-box;margin:auto!important;background:#262624!important;color:#f2efe8!important;
  --vb-page:#262624;--vb-surface:#30302c;--vb-raised:#35342f;--vb-border:#625d54;
  --vb-text:#f2efe8;--vb-muted:#c8c1b7;--vb-accent:#e3a187;--vb-success:#b7d4ac;--vb-danger:#ffd1c9;
}
#masthead {display:flex;justify-content:space-between;align-items:center;padding:24px 4px 18px;gap:20px;}
#masthead h1 {font-family:Georgia,'Times New Roman',serif;font-size:32px;font-weight:500;margin:0;color:var(--vb-text);letter-spacing:-.6px;}
#masthead p {margin:6px 0 0;color:var(--vb-muted);font-size:14px;}
.local-badge,.job-kind {border:1px solid #756757;border-radius:20px;padding:6px 12px;background:#3b342e;color:#f1c7ad;font-size:12px;font-weight:600;white-space:nowrap;}
.job-card {border:1px solid var(--vb-border);border-radius:14px;padding:24px 26px;background:var(--vb-surface);color:var(--vb-text);}
.job-card h2 {font-family:Georgia,'Times New Roman',serif;font-size:27px!important;font-weight:500!important;line-height:1.25;margin:8px 0 10px!important;overflow-wrap:anywhere;color:var(--vb-text)!important;}
.job-card p {line-height:1.6;}
.job-top {display:flex;justify-content:space-between;align-items:start;gap:12px;}
.eyebrow {font-size:12px;font-weight:700;letter-spacing:1.4px;color:var(--vb-accent);}
.job-card.failed {border-color:#c68f85;} .job-card.failed .eyebrow {color:var(--vb-danger);}
.job-card.done {border-color:#8faa84;} .job-card.done .eyebrow {color:var(--vb-success);}
.job-settings,.worker-line,.job-foot {font-size:13px;color:var(--vb-muted);line-height:1.6;}
.stages {display:flex;gap:12px;justify-content:space-between;flex-wrap:wrap;margin:22px 0;}
.step {display:flex;gap:8px;align-items:center;font-size:13px;color:var(--vb-muted);}
.step b {border-radius:50%;border:1px solid #82796d;background:#3b3933;color:#ddd7cd;min-width:25px;height:25px;display:grid;place-items:center;}
.step.active {font-weight:650;color:#f1c7ad;} .step.active b {background:#d99a7d;border-color:#d99a7d;color:#261e1a;}
.step.finished {color:var(--vb-success);} .step.finished b {background:#354132;border-color:#8faa84;color:#d2e5c9;}
.progress-label {display:flex;justify-content:space-between;gap:14px;font-size:14px;margin-bottom:9px;color:var(--vb-text);}
.job-progress {display:block;width:100%;height:9px;accent-color:var(--vb-accent);border:0;border-radius:12px;overflow:hidden;background:#514c43;}
.job-progress::-webkit-progress-bar {background:#514c43;border-radius:12px;}
.job-progress::-webkit-progress-value {background:#e3a187;border-radius:12px;transition:width .4s;}
.job-progress::-moz-progress-bar {background:#e3a187;}
.job-progress:not([value]) {background:linear-gradient(90deg,#514c43 20%,#e3a187 50%,#514c43 80%);background-size:200% 100%;animation:working 2s linear infinite;}
@keyframes working {to{background-position:-200% 0}}
@media(prefers-reduced-motion:reduce){.job-progress{animation:none!important;transition:none!important;}}
.job-message {font-size:14px;line-height:1.6;margin:12px 0;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--vb-text);}
.metrics {display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:14px 16px;padding:16px 0;border-top:1px solid var(--vb-border);border-bottom:1px solid var(--vb-border);margin:16px 0;}
.metric span {display:block;font-size:12px;color:var(--vb-muted);margin-bottom:6px;line-height:1.4;}
.metric strong {font-size:20px;font-weight:600;color:var(--vb-text);font-variant-numeric:tabular-nums;}
.current-passage {font-size:14px;margin:16px 0;padding:12px 15px;background:#38352f;border-left:3px solid var(--vb-accent);border-radius:4px;color:var(--vb-text);}
.current-passage p {margin:6px 0 0;line-height:1.6;color:#ddd7cd;}
.worker-line {line-height:1.8;} .job-foot {font-size:12px;margin-top:10px;}
#chapter-selector {max-height:280px;overflow-y:auto;}
.chapter-table {max-height:280px;overflow:auto;}
.chapter-table table {border-collapse:collapse;width:100%;font-size:13px;color:var(--vb-text);}
.chapter-table th,.chapter-table td {text-align:left;padding:11px;border-bottom:1px solid var(--vb-border);}
.chapter-table th {color:var(--vb-muted);font-weight:600;background:#35342f;}
#library-list {max-height:460px;overflow-y:auto;}
#library-list label {white-space:normal;line-height:1.5;}
#library-detail {overflow-wrap:anywhere;font-size:14px;color:var(--vb-muted);line-height:1.7;}
#library-detail h3 {font-family:Georgia,'Times New Roman',serif;font-size:25px;font-weight:500;color:var(--vb-text);margin:0 0 10px;}
#library-detail p {color:var(--vb-muted);margin:6px 0;}
#job-actions {margin:0;gap:10px;}
/* Gradio sets overflow:hidden on the container, which disables position:sticky. clip keeps
   the no-horizontal-scroll behaviour without creating a scroll container. */
.gradio-container {overflow:clip visible!important;overflow-x:clip!important;overflow-y:visible!important;}
#job-dashboard {padding:0!important;border:0!important;background:transparent!important;}
#job-dashboard .html-container,.step-head-wrap .html-container,.sub-title-wrap .html-container {padding:0!important;}
/* ---- Layout: steps on the left, create + live progress pinned on the right ---- */
#create-layout,#library-layout {align-items:flex-start!important;gap:24px;}
#steps {gap:18px!important;}
.step-card {border:1px solid #4a473f!important;border-radius:16px!important;background:#2b2b28!important;padding:20px!important;gap:14px!important;}
.step-head {display:flex;gap:14px;align-items:flex-start;margin:0 0 2px;}
.step-head h3 {margin:0;font-size:19px;font-weight:600;color:var(--vb-text);line-height:1.3;}
.step-head p {margin:4px 0 0;font-size:13.5px;color:var(--vb-muted);line-height:1.5;}
.step-num {flex:none;width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font-weight:700;font-size:14px;background:#d99a7d;color:#261e1a;}
.sub-card {border:1px solid #4a473f!important;border-radius:12px!important;background:#262624!important;padding:14px!important;gap:12px!important;}
.sub-title {margin:0;font-size:15px;font-weight:600;color:var(--vb-text);}
.compact-row {gap:10px!important;align-items:center!important;}
#cover-column {gap:8px!important;}
/* Narrator picker: a two-column list of voice "chips"; the card beside it plays the ready sample. */
#narrator-grid .wrap {display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px!important;}
#narrator-grid .wrap label {width:100%!important;margin:0!important;padding:10px 12px!important;border-radius:10px!important;line-height:1.35;white-space:normal!important;}
#narrator-card {position:sticky;top:12px;}
#narrator-name h3 {font-family:Georgia,'Times New Roman',serif;font-size:24px;font-weight:500;margin:0 0 4px;color:var(--vb-text);}
#narrator-name p {margin:0;color:var(--vb-muted);font-size:14px;line-height:1.5;}
.narrator-tag {display:inline-block;margin-top:8px;border:1px solid #756757;border-radius:20px;padding:3px 10px;background:#3b342e;color:#f1c7ad;font-size:12px;font-weight:600;}
#engine-pick .wrap {gap:8px!important;}
/* No inner scrolling here: Chromium fails to paint a scrolling box inside a sticky column. */
#side {position:sticky;top:12px;align-self:flex-start;gap:12px!important;flex-wrap:nowrap!important;}
#side > * {flex-shrink:0!important;}
#create-button {min-height:52px;font-size:17px!important;}
#side .job-card {padding:16px 18px;}
#side .job-card h2 {font-size:21px!important;margin:4px 0 6px!important;}
#side .stages {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:12px 0;}
#side .metrics {padding:10px 0;margin:10px 0;}
#side .job-message {margin:8px 0;}
#side .current-passage {margin:10px 0;padding:9px 12px;font-size:13px;}
#side .current-passage p {line-height:1.5;}
#side .worker-line {font-size:12px;line-height:1.6;}
#side .job-foot {font-size:11.5px;margin-top:6px;}
#side .metrics {grid-template-columns:repeat(3,minmax(0,1fr));gap:14px 12px;}
#side .metric strong {font-size:16px;white-space:nowrap;}
.side-note p {font-size:12.5px!important;}
#conversion-result {border:1px solid #625d54;border-radius:12px;padding:18px;background:#30302c;}
/* Dropdown menus are portalled in some Gradio versions. Give the popup its
   own opaque surface so underlying text never shows through the options. */
body .options {opacity:1!important;background:#35342f!important;border:1px solid #82796d!important;border-radius:9px!important;box-shadow:0 10px 30px #0007!important;}
body [role='listbox'] {background:#35342f!important;color:#f2efe8!important;}
body [role='option'] {background:#35342f!important;color:#f2efe8!important;white-space:normal!important;line-height:1.5;}
body [role='option']:hover,body [role='option'].active,body [role='option'][aria-selected='true'] {background:#49382f!important;color:#fff0e6!important;}

.section-heading {margin:6px 0!important;} .muted {color:var(--vb-muted);font-size:13px;}
/* Native components, popovers and read-only fields must remain legible. */
.gradio-container input,.gradio-container textarea {color:#f2efe8!important;caret-color:#e3a187;}
.gradio-container input::placeholder,.gradio-container textarea::placeholder {color:#b5ada1!important;opacity:1;}
.gradio-container input:disabled,.gradio-container textarea:disabled {color:#c8c1b7!important;-webkit-text-fill-color:#c8c1b7;opacity:1;}
.gradio-container button:disabled {background:#3b3933!important;border-color:#706a60!important;color:#b5ada1!important;opacity:1!important;cursor:not-allowed;box-shadow:none!important;}
.gradio-container button:disabled:hover {background:#3b3933!important;}
.gradio-container button:focus-visible,.gradio-container a:focus-visible,.gradio-container [role='tab']:focus-visible {outline:2px solid #e3a187!important;outline-offset:3px;}
.gradio-container .tab-nav {border-bottom:1px solid #625d54!important;padding-bottom:4px;}
.gradio-container .tab-nav button {color:#c8c1b7!important;font-size:14px;}
.gradio-container .tab-nav button.selected,.gradio-container .tab-nav button[aria-selected='true'] {color:#f1c7ad!important;border-bottom:2px solid #e3a187!important;background:#35302b!important;}
.gradio-container .prose {color:#ddd7cd;line-height:1.65;}
.gradio-container .prose h3 {color:#f2efe8;font-size:18px;font-weight:600;}
.gradio-container .prose strong {color:#f2efe8;}
.gradio-container .prose a {color:#efb89a;}
.gradio-container audio {color-scheme:dark;}
@media(max-width:900px){
  #side {position:static!important;max-height:none!important;overflow:visible!important;}
}
@media(max-width:700px){
  .gradio-container .row > .column,.gradio-container .row > .form {min-width:0!important;flex-basis:100%!important;}
  .gradio-container .block {min-width:0!important;}
  .gradio-container .tab-nav,.gradio-container [role='tablist'] {flex-wrap:wrap!important;overflow:visible!important;}
  .gradio-container [role='tab'] {min-width:0!important;max-width:100%!important;white-space:normal!important;flex:1 1 100%!important;text-align:left;}

  #job-actions > button {flex:1 1 100%!important;min-height:42px;}
  #side {position:static;max-height:none;overflow:visible;}
  #side .metrics {grid-template-columns:repeat(2,minmax(0,1fr));}
  #narrator-grid .wrap {grid-template-columns:1fr;}
  #narrator-card {position:static;}
  #side .metric strong {white-space:normal;}
  .gradio-container .label-wrap {text-align:left!important;justify-content:space-between!important;}
  .step-card {padding:14px!important;}
  #conversion-result {padding:12px;}

  #masthead {align-items:start;padding-top:16px;} #masthead h1 {font-size:27px;}
  .local-badge {display:none;} .job-card {padding:18px;} .job-card h2 {font-size:24px!important;}
  .metrics {grid-template-columns:repeat(2,1fr);gap:14px;}
  .stages {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;}
  .step {font-size:12px;} .metric strong {font-size:18px;} .job-kind {font-size:11px;padding:5px 8px;}
}
'''
