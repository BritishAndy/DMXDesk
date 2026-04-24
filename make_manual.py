"""
Generate DMX Desk Emulator user manual PDFs:
  - DMX_Desk_Manual.pdf        (full manual)
  - DMX_Desk_Quick_Reference.pdf (one-page quick ref)
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)

GOLD     = colors.HexColor("#ffcc00")
AMBER    = colors.HexColor("#ddaa00")
DIM_GREY = colors.HexColor("#aaaaaa")
MID_GREY = colors.HexColor("#666666")
WHITE    = colors.white

def make_styles():
    base = ParagraphStyle('base', fontName='Helvetica', fontSize=10,
                           textColor=colors.black, leading=14)
    return dict(
        title     = ParagraphStyle('T',  parent=base, fontSize=22,
                                    fontName='Helvetica-Bold', textColor=GOLD,
                                    leading=28, alignment=TA_CENTER, spaceAfter=8),
        subtitle  = ParagraphStyle('St', parent=base, fontSize=14,
                                    textColor=DIM_GREY, alignment=TA_CENTER, spaceAfter=4),
        section   = ParagraphStyle('S',  parent=base, fontSize=14,
                                    fontName='Helvetica-Bold', textColor=GOLD,
                                    spaceBefore=14, spaceAfter=4),
        subsection= ParagraphStyle('Ss', parent=base, fontSize=11,
                                    fontName='Helvetica-Bold', textColor=AMBER,
                                    spaceBefore=8, spaceAfter=3),
        body      = ParagraphStyle('B',  parent=base, fontSize=9,
                                    textColor=colors.HexColor("#222222"),
                                    leading=13, spaceAfter=4),
        note      = ParagraphStyle('N',  parent=base, fontSize=8,
                                    textColor=MID_GREY, leading=12,
                                    leftIndent=8, spaceAfter=3),
        kbd       = ParagraphStyle('K',  parent=base, fontSize=9,
                                    fontName='Courier',
                                    textColor=colors.HexColor("#224422"),
                                    leading=13, spaceAfter=2),
    )

ST = make_styles()

def p(text, style='body'):   return Paragraph(text, ST[style])
def sp(n=4):                 return Spacer(1, n * mm)
def hr():
    return HRFlowable(width="100%", thickness=0.5,
                      color=colors.HexColor("#cccccc"), spaceAfter=4)
def section_title(text):     return KeepTogether([hr(), p(text, 'section')])
def sub(text):               return p(text, 'subsection')

def key_table(rows, col_widths=None):
    data = [[p('<b>' + k + '</b>', 'body'), p(v, 'body')] for k, v in rows]
    cw = col_widths or [55*mm, 110*mm]
    t = Table(data, colWidths=cw)
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (0,-1), colors.HexColor("#f0f0f0")),
        ('FONTNAME',      (0,0), (0,-1), 'Courier'),
        ('FONTSIZE',      (0,0), (-1,-1), 9),
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('ROWBACKGROUNDS',(0,0), (-1,-1), [WHITE, colors.HexColor("#f8f8f8")]),
        ('GRID',          (0,0), (-1,-1), 0.25, colors.HexColor("#cccccc")),
        ('TOPPADDING',    (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING',   (0,0), (-1,-1), 5),
        ('RIGHTPADDING',  (0,0), (-1,-1), 5),
    ]))
    return t


def build_full_manual(path):
    doc = SimpleDocTemplate(path, pagesize=A4,
                             leftMargin=18*mm, rightMargin=18*mm,
                             topMargin=18*mm, bottomMargin=18*mm,
                             title="DMX Desk Emulator - User Manual",
                             author="DMX Desk")
    story = []

    story += [
        sp(20), p("DMX Desk Emulator", 'title'),
        p("User Manual", 'subtitle'), sp(2),
        p("v1.0  -  Art-Net DMX Control Software for macOS", 'subtitle'),
        sp(10),
        HRFlowable(width="60%", thickness=2, color=GOLD, hAlign='CENTER', spaceAfter=8),
        sp(4),
        p("A software lighting desk that outputs DMX over Art-Net UDP. "
          "Supports dimmers, RGB, RGBW and complex multi-channel fixtures, "
          "relay/digital fixtures, submasters, scenes with fade times, "
          "a built-in clock and timer, live DMX grid monitor, QLab OSC integration, "
          "and a full patch editor with Open Fixture Library support.", 'body'),
        PageBreak(),
    ]

    story += [
        p("Contents", 'section'),
        key_table([
            ("1. Getting Started",        "Launching the app, Art-Net setup"),
            ("2. The Main Interface",     "Header, fixture panel, footer"),
            ("3. Fixtures",               "Faders, solos, colour swatches"),
            ("4. Digital Fixtures",       "Relay and on/off fixture control"),
            ("5. Grand Master",           "Overall level control"),
            ("6. Submasters",             "Group level control"),
            ("7. Scene Memory",           "Recording, recalling, naming, colouring"),
            ("8. Fade Times",             "Setting, using and stopping fades"),
            ("9. Solo & Record",          "Partial scene recording"),
            ("10. Copy & Paste",          "Copying fixture states"),
            ("11. Group Selection",       "Ganging fixtures together"),
            ("12. Clock & Timers",        "Clock, stopwatch, countdown"),
            ("13. Timing Logger",          "Scene cue timing and CSV export"),
            ("14. DMX Grid",              "Live DMX output monitor in the fixture panel"),
            ("15. Patch Editor",          "Managing the fixture patch"),
            ("16. Fixture Definitions",   "JSON fixture files explained"),
            ("17. Open Fixture Library",  "Importing fixtures from OFL"),
            ("18. Settings",              "Art-Net, appearance, behaviour, OSC"),
            ("19. Save & Load",           "Saving shows and patches"),
            ("21. QLab Integration",      "OSC control from QLab"),
            ("22. Monitoring Tools",       "monitor_gui.py and monitor.py"),
            ("23. Keyboard & Mouse",      "Quick reference"),
        ], col_widths=[60*mm, 105*mm]),
        PageBreak(),
    ]

    story += [
        section_title("1. Getting Started"),
        sub("Launching"),
        p("Double-click <b>DMX Desk.app</b> in Finder, or from Terminal:"),
        p("  python3 desk.py              - launches with default settings", 'kbd'),
        p("  python3 desk.py --dry-run    - no Art-Net output (testing)", 'kbd'),
        sp(2), sub("First Launch"),
        p("On first launch the app creates <b>desk_prefs.json</b> alongside desk.py "
          "to store window size, settings and the last loaded show file. "
          "Your patch file <b>patch.json</b> must be in the same folder."),
        sp(2), sub("Art-Net Setup"),
        p("Configure the target IP, port (default 6454) and universe (default 0) "
          "in Settings. The ArtNet indicator shows green when the node responds to ping."),
        sp(2), sub("On Exit"),
        p("A final DMX frame is sent with each fixture's default channel values "
          "so lights hold their default state rather than snapping to zero."),
    ]

    story += [
        section_title("2. The Main Interface"),
        sub("Top Bar"),
        key_table([
            ("DMX DESK EMULATOR v...", "App title and version."),
            ("Show: filename",         "Currently loaded show file (green)."),
            ("ArtNet",                 "Green = node reachable, red = unreachable, grey = dry run."),
            ("? Help",                 "Opens this manual."),
            ("Edit Patch",             "Opens the patch editor."),
            ("Settings",               "Opens the settings dialog."),
        ]),
        sp(3), sub("Footer - Scene Buttons"),
        p("30 scene buttons in two rows of 15. Left click to recall. "
          "Right double-click to edit name and colour. Ctrl+drag to reorder."),
        sp(3), sub("Footer - Controls Strip"),
        key_table([
            ("STOP FADE",    "Interrupts a running fade, leaving faders where they are. Lights amber during an active fade."),
            ("CLEAR SOLOS",  "Clears amber solo buttons. Locks are unaffected."),
            ("CLEAR LOCKS",  "Clears all red channel locks across all fixtures."),
            ("SAVE / LOAD",  "Save or load a show file."),
            ("- / +",        "Zoom 25% to 175% in 5% steps."),
            ("GRAND MASTER", "Scales all DMX output proportionally."),
            ("GRAND MASTER",  "Scales all DMX output proportionally."),
        ]),
    ]

    story += [
        section_title("3. Fixtures"),
        sub("Master Fader"),
        p("The large vertical fader controls intensity. Double-click the value to type directly."),
        sp(2), sub("Colour Faders"),
        p("R/G/B/W/A/UV channels appear below the master. "
          "The master fader track shows the live colour mix as a swatch."),
        sp(2), sub("Non-Colour Channels"),
        p("Channels such as Strobe, Zoom, Mode appear beside the master. "
          "Named-range channels show the current mode name."),
        sp(2), sub("Solo Buttons"),
        p("Each channel has a small S button for partial recording. "
          "Solo fix solos all channels and illuminates all S buttons."),
        sp(2), sub("Submaster Tint"),
        p("Amber highlight border when a submaster is scaling the fixture below 100%."),
    ]

    story += [
        section_title("4. Digital Fixtures"),
        p("Fixtures where all channels are binary (On/Off) show a digital faceplate "
          "with toggle buttons instead of faders."),
        sp(2),
        key_table([
            ("Dark grey",  "Channel is Off."),
            ("Bright green","Channel is On."),
            ("Click button","Toggle on or off."),
            ("layout",     'Set "layout": "vertical" or "horizontal" in the fixture JSON. '
                           'Omit for auto (horizontal if 3 or fewer channels).'),
        ]),
        sp(2),
        p("Digital fixture state is fully stored and recalled in scenes."),
    ]

    story += [
        section_title("5. Grand Master"),
        p("The GM fader scales all fixture output. At 0% all channels output zero. "
          "Restoring GM returns to the same levels."),
    ]

    story += [
        section_title("6. Submasters"),
        p("Submasters control named groups of fixtures. "
          "An amber border indicates below 100%. "
          "Fixtures being scaled show an amber highlight border."),
        sp(2),
        p('Define in patch.json: {"type": "submaster", "name": "Wash Sub", '
          '"targets": ["Wash 1", "Wash 2"]}', 'kbd'),
    ]

    story += [
        section_title("7. Scene Memory"),
        sub("Recording"),
        p("Set levels then click REC. If solos are active a dialog asks whether to "
          "clear solos and record all, record partial, or cancel."),
        sp(2), sub("Recalling"),
        p("Click a scene button. Buttons are disabled during a fade. "
          "Use STOP FADE to interrupt."),
        sp(2), sub("Right-click panel"),
        p("Right-click (or Ctrl+click on a trackpad) any scene button to open the scene panel. "
          "The button highlights blue while open. The panel contains:"),
        key_table([
            ("Name",               "Edit the scene name."),
            ("Button colour",      "Choose or clear the button tint colour."),
            ("Fade (s)",           "Set the fade time for this scene."),
            ("Record",             "Record current output to this scene."),
            ("Save name/colour",   "Save name and colour without recording."),
            ("Clear scene",        "Clear the scene (shown only if scene exists)."),
        ]),
        sp(2), sub("Highlights"),
        key_table([
            ("Gold",  "Last recalled scene (left-click)."),
            ("Blue",  "Scene with context panel open."),
        ]),
        sp(2), sub("Reordering"),
        p("Ctrl+drag a scene button to swap it with another slot. "
          "Data, name and colour all move together."),
        sp(2), sub("Auto-save"),
        p("Scenes save automatically on every change to the currently loaded show file."),
    ]

    story += [
        section_title("8. Fade Times"),
        p("The Fade (s) entry sets the fade time (decimals allowed). "
          "Each scene stores its own fade time."),
        sp(2), sub("Stopping a Fade"),
        p("STOP FADE lights amber during a fade. "
          "Pressing it halts the fade immediately at the current fader positions "
          "and re-enables the scene buttons."),
    ]

    story += [
        section_title("9. Solo & Record (Partial Scenes)"),
        sub("Solo button states"),
        key_table([
            ("S — dark",   "Off (default)."),
            ("S — amber",  "Soloed. Included in partial scene record."),
            ("S — red",    "Locked. Excluded from all scene recalls until unlocked."),
        ]),
        sp(2),
        p("Click S to cycle: off to solo to locked and back to off. "
          "The fixture Solo fix button follows the same cycle for all channels at once."),
        sp(2), sub("Recording and recalling"),
        key_table([
            ("REC + solos",   "Dialog: clear solos and record all / record partial / cancel."),
            ("CLEAR SOLOS",   "Clears amber solos. Red locks are unaffected."),
            ("CLEAR LOCKS",   "Clears all red locks across all fixtures."),
            ("Scene recall",  "Locked channels are silently skipped. "
                               "Fixture solo lock excludes the entire fixture."),
            ("Illuminate",    "Scene recall illuminates amber solos for channels stored in the scene."),
        ]),
    ]

    story += [
        section_title("10. Copy & Paste"),
        key_table([
            ("Ctrl+click fixture",  "Copy state. Compatible fixtures highlight green."),
            ("Click green",         "Paste copied state."),
            ("Escape",              "Cancel paste mode."),
        ]),
    ]

    story += [
        section_title("11. Group Selection"),
        key_table([
            ("Shift+click 1st",  "Selects the reference fixture."),
            ("Shift+click 2nd+", "Fades fixture to match reference over 1 second, then joins group."),
            ("Move any master",  "All grouped fixtures track together."),
            ("Click / Escape",   "Clears the group."),
        ]),
    ]

    story += [
        section_title("12. Clock & Timers"),
        p('Add to patch: {"type": "clock", "name": "Show Clock", "row": 1}', 'kbd'),
        sp(2), sub("Clock"), p("Shows current time HH:MM:SS."),
        sub("Stopwatch"), p("START/STOP, LAP, RST."),
        sub("Countdown"), p("Enter mm:ss. Last 10s flash amber. At zero panel flashes red."),
        sp(2), p("Timer state is preserved across zoom changes.", 'note'),
    ]

    story += [
        section_title("13. Timing Logger"),
        p("The Timing Logger records the time of each scene recall during a show or rehearsal, "
          "allowing you to annotate your script with accurate cue timings. "
          "Add it to your patch as a standalone widget:"),
        p('  {"type": "timinglogger", "name": "Timing Logger", "row": 1}', 'kbd'),
        sp(2),
        sub("Controls"),
        key_table([
            ("START",      "Begin logging. First scene press becomes time 00:00:00."),
            ("STOP",       "Pause logging without clearing the log."),
            ("EXPORT",     "Save the log as a CSV file."),
            ("RST",        "Clear the log (confirms if entries exist)."),
        ]),
        sp(2),
        sub("Log display"),
        p("Each scene recall is shown as a row: elapsed time, slot number, and scene name. "
          "The log scrolls automatically as entries accumulate."),
        sp(2),
        sub("CSV format"),
        p("Exported CSV contains: Date/Time, Slot, Scene Name, Elapsed time."),
        p('  30-04-26 19:32, 5, "Act 1 Scene 1", 00:00:00', 'kbd'),
        p('  30-04-26 19:35, 7, "Act 1 Scene 2", 00:03:02', 'kbd'),
        sp(2),
        sub("On close"),
        p("If the app is closed with unsaved timing entries, a dialog offers to export "
          "before closing.", 'note'),
    ]

    story += [
        section_title("14. DMX Grid"),
        p("The DMX Grid is an optional panel that can be added to the fixture area. "
          "It shows all 512 DMX output channels as a compact 32x16 grid, "
          "reading directly from the desk output — no network monitoring needed."),
        sp(2),
        p('Add via <b>+ Add DMX Grid</b> in the patch editor, or manually:', 'body'),
        p('  {"type": "dmxgrid", "name": "DMX Grid", "row": 1}', 'kbd'),
        sp(2),
        sub("Colour Coding"),
        key_table([
            ("Green",  "Channel value is rising."),
            ("Red",    "Channel value is falling."),
            ("Blue",   "Channel has been steady for ~1.5 seconds."),
            ("Dark",   "Channel is at zero."),
        ]),
        sp(2),
        sub("Tooltip"),
        p("Hover over any cell to see the channel number, fixture name and current value "
          "in the tooltip bar above the colour key."),
        sp(2),
        p("Scales with zoom and updates at 10Hz. Useful for confirming what DMX "
          "is being sent during fades or when submasters are active.", 'note'),
    ]

    story += [
        section_title("15. Patch Editor"),
        sub("Selecting"),
        key_table([
            ("Single-click",   "Select row."),
            ("Shift+click",    "Multi-select."),
            ("Double-click",   "Edit dialog (fields shown/hidden by type)."),
        ]),
        sp(2), sub("Adding"),
        key_table([
            ("+ Add Fixture",    "New fixture at next free address."),
            ("+ Add Sub",        "New submaster."),
            ("+ Add Divider",    "Visual separator."),
            ("+ Add Clock",      "Clock/timer widget."),
            ("+ Add DMX Grid",   "Live DMX output grid monitor."),
            ("+ Add Timing Logger", "Cue timing logger with CSV export."),
        ]),
        sp(2), sub("Other"),
        key_table([
            ("Up / Down",          "Reorder (multi-select supported)."),
            ("Delete",             "Delete selected (with confirmation)."),
            ("Edit Fixture Def",   "Open fixture JSON in built-in editor."),
            ("Create Fixture",     "New fixture from template with inline help."),
            ("Find Fixture",       "Import from Open Fixture Library."),
            ("Save & Reload",      "Save patch.json and reload immediately."),
        ]),
    ]

    story += [
        section_title("16. Fixture Definitions"),
        sub("Channel Fields"),
        key_table([
            ("label",   "Channel name. R/G/B/W/A/UV for colour channels."),
            ("master",  "true for the main intensity channel."),
            ("default", "DMX value on startup and on app exit (0-255)."),
            ("range",   '[0,255] numeric or {"0-127":"Off","128-255":"On"} named.'),
            ("unit",    '"%" percentage, "raw" DMX value, "named" mode labels.'),
            ("show",    "false to hide the channel (sends default silently)."),
        ]),
        sp(2), sub("Top-Level Fields"),
        key_table([
            ("colour", "Hex colour for the faceplate background."),
            ("layout", '"vertical" or "horizontal" for digital fixtures.'),
        ]),
    ]

    story += [
        section_title("17. Open Fixture Library"),
        key_table([
            ("First use",    "Fetches index from GitHub. Cached in ofl_fixtures.json."),
            ("Manufacturer", "Filter by manufacturer (e.g. chauvet, robe)."),
            ("Search",       "Shows up to 100 results."),
            ("Import",       "Saves fixture JSON to fixtures/."),
            ("Refresh DB",   "Re-fetches index from GitHub."),
        ]),
    ]

    story += [
        section_title("18. Settings"),
        sub("Art-Net"),
        key_table([
            ("Target IP", "IP address of your Art-Net node."),
            ("Port",      "UDP port (default 6454)."),
            ("Universe",  "Art-Net universe 0-15."),
        ]),
        sp(2), sub("Appearance"),
        key_table([
            ("Startup zoom",    "Default zoom on launch (25%-175%)."),
            ("Scene layout",    "paired = odd/even rows; sequential = 1-15 / 16-30."),
            ("Reload last show","Auto-load last show file on startup."),
        ]),
        sp(2), sub("Behaviour"),
        key_table([
            ("DMX interval", "Update rate in ms (default 25 = 40Hz)."),
            ("Fade steps",   "Interpolation resolution (default 40)."),
        ]),
        sp(2), sub("OSC Input"),
        key_table([
            ("Enable OSC", "Enable the OSC listener."),
            ("OSC Port",   "UDP port for incoming OSC (default 8000)."),
        ]),
    ]

    story += [
        section_title("19. Save & Load"),
        sub("Show Files"),
        p("Scenes save automatically to the loaded show file on every change. "
          "The filename appears in the top bar. "
          "Use SAVE to save to a new file, LOAD to open a different show. "
          "Enable Reload last show in Settings to auto-load on startup."),
        sp(2), sub("Multiple Shows"),
        p("Keep a shows/ folder with one JSON per production. "
          "The patch stays the same for the same venue; only the scenes file changes."),
    ]

    story += [
        section_title("20. Sequences"),
        p("A sequence is a scene slot that automatically fires a series of scene recalls "
          "with per-step fade times and delays. Sequences appear as teal-coloured scene "
          "buttons and are triggered identically to regular scenes — by left-click, "
          "OSC, or the scene Go button."),
        sp(2),
        sub("Creating a Sequence"),
        p("Right-click any scene button and choose <b>▶ Convert to sequence</b>, "
          "or right-click an existing sequence and choose <b>✎ Edit steps</b>. "
          "The sequence editor opens where you can name the sequence and enter steps."),
        sp(2),
        sub("Step Format"),
        p("Enter one step per line in the text box:"),
        p("  scene  fade(s)  delay(s)  [+Fixture=val ...]", "kbd"),
        sp(2),
        key_table([
            ("scene",         "Scene slot number to recall. Omit for a channel-only step."),
            ("fade",          "Fade time in seconds for this step."),
            ("delay",         "Pause in seconds after the fade completes before the next step."),
            ("+Fixture=val",  "Set a fixture master to a DMX value (0-255). "
                               "Fixture name must match the patch exactly (spaces allowed). "
                               "Multiple assignments per line are supported."),
            ("# comment",     "Lines starting with # are ignored."),
        ]),
        sp(2),
        sub("Examples"),
        p("  2  0.0  0.5                        — recall scene 2 instant, wait 0.5s", "kbd"),
        p("  5  3.0  0.0                        — recall scene 5 with 3s fade", "kbd"),
        p("  +House Lights=0  1.0  0.5          — fade house lights out over 1s, wait 0.5s", "kbd"),
        p("  5  3.0  0.0  +House Lights=128     — recall scene 5 and set house lights", "kbd"),
        sp(2),
        sub("Running and Stopping"),
        key_table([
            ("Left click",              "Run the sequence."),
            ("Any scene button",        "Stops the running sequence and fires that scene."),
            ("STOP FADE",               "Stops the running sequence at the current step."),
            ("Teal button colour",      "Indicates a sequence slot."),
            ("Gold button colour",      "Last recalled sequence or scene."),
        ]),
        sp(2),
        sub("Converting Back"),
        p("Right-click a sequence button and choose <b>↩ Convert to regular scene</b> "
          "to restore it as a normal empty scene slot."),
    ]
    story += [

        section_title("21. QLab Integration"),
        p("The desk receives OSC from QLab to recall scenes automatically. "
          "Art-Net HTP merge at the node allows both to send simultaneously."),
        sp(2), sub("QLab Setup"),
        p("In QLab Settings > Network add a destination: type OSC, "
          "address = desk Mac IP, port = 8000, protocol UDP. "
          "Add a Network cue with the appropriate OSC message."),
        sp(2), sub("OSC Commands"),
        key_table([
            ("/desk/scene/recall 3",          "Recall scene slot 3."),
            ('/desk/scene/recall "Name"',     "Recall by name (string argument)."),
            ("/desk/scene/recall/Name",       "Recall by name (underscores = spaces)."),
            ("/desk/scene/select 3",          "Select slot without recalling."),
            ("/desk/scene/go",                "Fire selected scene."),
            ("/desk/grandmaster 80",          "Set GM to 80%."),
            ("/desk/fader/Wash1 75",          "Set fixture master to 75%."),
        ]),
        sp(2), sub("Workflow"),
        p("Program all looks as scenes in the desk. "
          "In QLab add an OSC cue alongside each lighting cue. "
          "The operator can grab any fader to adjust live at any time."),
    ]

    story += [
        section_title("22. Monitoring Tools"),
        sub("monitor_gui.py — GUI Monitor (recommended)"),
        p("A tkinter companion application for testing and diagnosing DMX output. "
          "Run alongside desk.py on the same machine or any Mac on the same network."),
        sp(2),
        p("  python3 monitor_gui.py", 'kbd'),
        p("  python3 monitor_gui.py --patch patch.json   — show fixture names", 'kbd'),
        p("  python3 monitor_gui.py --port 6454 --universe 0", 'kbd'),
        sp(2),
        key_table([
            ("Channel Grid tab",   "32x16 grid of all 512 DMX channels. "
                                   "Colour coded: green=rising, red=falling, "
                                   "blue=steady, dark=zero."),
            ("Fixture View tab",   "One row per fixture showing all channel values "
                                   "with fixture colour coding from patch.json."),
            ("Hover (grid)",       "Shows channel number, fixture name and value "
                                   "in the tooltip bar below the grid."),
            ("HTP merge",          "Receives from multiple Art-Net sources and "
                                   "displays the highest value per channel."),
        ]),
        sp(3),
        sub("monitor.py — Terminal Monitor"),
        p("A lightweight terminal-based monitor, useful for headless or SSH use."),
        sp(2),
        p("  python3 monitor.py", 'kbd'),
        p("  python3 monitor.py --no-merge   — last packet wins", 'kbd'),
        p("  python3 monitor.py --threshold 5", 'kbd'),
    ]

    story += [
        section_title("23. Keyboard & Mouse"),
        key_table([
            ("Ctrl+click fixture",       "Copy fixture state"),
            ("Click green fixture",      "Paste copied state"),
            ("Shift+click fixture",      "Add to / remove from group"),
            ("Escape",                   "Cancel paste / clear group"),
            ("Left click scene",         "Recall scene"),
            ("Right-click / Ctrl+click scene", "Open scene context panel"),
            ("Click S button",               "Cycle: off / solo (amber) / locked (red)"),
            ("Ctrl+drag scene",          "Reorder scene buttons"),
            ("Double-click fader value", "Type value directly"),
            ("Cmd+S (fixture editor)",   "Save fixture definition"),
            ("Return (in dialogs)",      "Confirm / apply"),
        ]),
        PageBreak(),
    ]

    doc.build(story)
    print(f"Full manual written to {path}")


def build_quick_ref(path):
    doc = SimpleDocTemplate(path, pagesize=A4,
                             leftMargin=14*mm, rightMargin=14*mm,
                             topMargin=14*mm, bottomMargin=14*mm,
                             title="DMX Desk - Quick Reference")
    story = []

    story += [
        p("DMX Desk Emulator - Quick Reference", 'title'),
        HRFlowable(width="100%", thickness=1, color=GOLD, spaceAfter=4),
        sp(1),
    ]

    # Build a single flat table for the quick reference
    # Each section is a heading row + data rows, two sections side by side
    HEAD_BG  = colors.HexColor("#222222")
    HEAD_FG  = GOLD
    KEY_BG   = colors.HexColor("#f0f0f0")
    ALT_BG   = colors.HexColor("#f8f8f8")

    fnt_h = ("Helvetica-Bold", 8)
    fnt_k = ("Courier",        7)
    fnt_v = ("Helvetica",      7)

    def qr_section(title, rows):
        """Returns list of (key_text, val_text) with a title sentinel."""
        return [("__HEAD__", title)] + list(rows)

    left_data = (
        qr_section("SCENES", [
            ("Left click",            "Recall scene"),
            ("Right-click/Ctrl+click","Open scene panel"),
            ("Ctrl+drag",             "Reorder"),
            ("STOP FADE",             "Interrupt running fade"),
            ("Gold",                  "Last recalled"),
            ("Blue",                  "Panel open"),
        ]) +
        qr_section("SOLOS & LOCKS", [
            ("S — amber",          "Solo channel"),
            ("S — red",            "Lock (exclude from recall)"),
            ("Solo fix",           "Cycle all channels"),
            ("CLEAR SOLOS",        "Clear amber solos"),
            ("CLEAR LOCKS",        "Clear red locks"),
        ]) +
        qr_section("COPY & PASTE", [
            ("Ctrl+click",         "Copy fixture state"),
            ("Click green",        "Paste to fixture"),
            ("Escape",             "Cancel paste"),
        ]) +
        qr_section("GROUP CONTROL", [
            ("Shift+click 1st",    "Set reference fixture"),
            ("Shift+click 2nd+",   "Fade to match, join group"),
            ("Move any master",    "All track together"),
            ("Click / Escape",     "Clear group"),
        ])
    )

    right_data = (
        qr_section("PATCH EDITOR", [
            ("Double-click row",   "Edit entry"),
            ("Shift+click",        "Multi-select"),
            ("+ Add Fixture",      "New fixture"),
            ("Create Fixture",     "New from template"),
            ("Edit Fixture Def",   "Edit fixture JSON"),
            ("Find Fixture",       "Import from OFL"),
            ("Save & Reload",      "Apply all changes"),
        ]) +
        qr_section("SETTINGS", [
            ("Art-Net IP/Port",    "Target node address"),
            ("Universe",           "0-15"),
            ("Scene layout",       "paired / sequential"),
            ("Reload last show",   "Auto-load on startup"),
            ("OSC Port",           "Default 8000"),
        ]) +
        qr_section("QLAB OSC COMMANDS", [
            ("/desk/scene/recall N",  "Recall slot N"),
            ("/desk/scene/recall/Name","Recall by name"),
            ("/desk/scene/go",         "Fire selected scene"),
            ("/desk/grandmaster 80",   "Set GM to 80%"),
            ("/desk/fader/Name 75",    "Set fixture to 75%"),
        ]) +
        qr_section("CLOCK WIDGET", [
            ("START/STOP",         "Stopwatch / countdown"),
            ("LAP",                "Record lap time"),
            ("RST",                "Reset"),
            ("Flashing red",       "Countdown at zero"),
        ])
    )

    # Pad to equal length
    while len(left_data) < len(right_data):
        left_data = list(left_data) + [("", "")]
    while len(right_data) < len(left_data):
        right_data = list(right_data) + [("", "")]

    CW = [22*mm, 60*mm, 22*mm, 60*mm]  # key / val / key / val

    table_data = []
    style_cmds = [
        ('FONTSIZE',     (0,0), (-1,-1), 7),
        ('TOPPADDING',   (0,0), (-1,-1), 2),
        ('BOTTOMPADDING',(0,0), (-1,-1), 2),
        ('LEFTPADDING',  (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
        ('VALIGN',       (0,0), (-1,-1), 'TOP'),
        ('GRID',         (0,0), (-1,-1), 0.25, colors.HexColor("#dddddd")),
    ]

    for i, ((lk, lv), (rk, rv)) in enumerate(zip(left_data, right_data)):
        if lk == "__HEAD__":
            row = [Paragraph('<b>' + lv + '</b>', ParagraphStyle('qh',
                    fontName='Helvetica-Bold', fontSize=7, textColor=GOLD,
                    leading=9)),
                   Paragraph('', ST['body']),
                   Paragraph('<b>' + rv + '</b>' if rv else '', ParagraphStyle('qh2',
                    fontName='Helvetica-Bold', fontSize=7, textColor=GOLD,
                    leading=9)),
                   Paragraph('', ST['body'])]
            style_cmds += [
                ('BACKGROUND',  (0,i), (1,i), colors.HexColor("#222222")),
                ('BACKGROUND',  (2,i), (3,i), colors.HexColor("#222222")),
                ('SPAN',        (0,i), (1,i)),
                ('SPAN',        (2,i), (3,i)),
            ]
        else:
            row = [
                Paragraph(lk, ParagraphStyle('qk', fontName='Courier',
                           fontSize=7, leading=9)),
                Paragraph(lv, ParagraphStyle('qv', fontName='Helvetica',
                           fontSize=7, leading=9)),
                Paragraph(rk, ParagraphStyle('qk2', fontName='Courier',
                           fontSize=7, leading=9)),
                Paragraph(rv, ParagraphStyle('qv2', fontName='Helvetica',
                           fontSize=7, leading=9)),
            ]
            bg = KEY_BG if i % 2 == 0 else ALT_BG
            style_cmds += [
                ('BACKGROUND', (0,i), (0,i), bg),
                ('BACKGROUND', (2,i), (2,i), bg),
            ]
        table_data.append(row)

    qr_table = Table(table_data, colWidths=CW)
    qr_table.setStyle(TableStyle(style_cmds))
    story.append(qr_table)

    story += [
        sp(2),
        HRFlowable(width="100%", thickness=0.5, color=GOLD, spaceAfter=3),
        p("Files: patch.json (patch)  |  shows/*.json (scenes)  |  "
          "desk_prefs.json (settings)  |  fixtures/ (fixture defs)  |  "
          "ofl_fixtures.json (OFL cache)", 'note'),
    ]

    doc.build(story)
    print(f"Quick reference written to {path}")


if __name__ == "__main__":
    import os
    base = os.path.dirname(os.path.abspath(__file__))
    build_full_manual(os.path.join(base, "DMX_Desk_Manual.pdf"))
    build_quick_ref(os.path.join(base, "DMX_Desk_Quick_Reference.pdf"))
