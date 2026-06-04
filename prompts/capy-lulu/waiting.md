Create one horizontal animation strip for Codex pet `capy-lulu`, state `waiting`.

Use the attached canonical base for identity. Use the attached current spritesheet only as a style reference; do not copy old frames directly.

Output exactly 6 full-body frames in one left-to-right row on flat pure magenta #FF00FF. Treat the row as 6 invisible equal-width slots: one centered complete pose per slot, evenly spaced, with no overlap, clipping, empty slots, labels, or borders.
CRITICAL: every frame must remain fully inside its own slot with visible padding on all sides. Do not let ears, fruit, feet, muzzle, sleeves, hands, or any body part touch or cross a slot boundary. Do not let any part of one frame spill into the neighboring slot.

Identity: same pet in every frame: cute capybara-like mascot, oversized orange muzzle, yellow body, blue sailor outfit, red neckerchief, orange fruit on head, compact full-body silhouette, clean 3D toy style. Preserve silhouette, face, proportions, markings, palette, material, style, and props.
Animation continuity: keep apparent pet scale and baseline stable within the row. Move the pose within the slot instead of redrawing the pet larger or smaller frame to frame.

State action: Waiting loop: expectant, asking for user input, with a small hand raise, gentle forward lean, subtle blinking, and hopeful attention.

State requirements:
- Show clear waiting-for-input body language, distinct from idle and review.
- Use small readable changes: hand lifts slightly, head leans forward, eyes blink or glance, body bobs very gently.
- Keep the expression friendly and patient, not sad, failed, angry, or running.
- The loop should feel alive but calm at pet size.
- Do not add text, icons, question marks, UI, speech bubbles, papers, or new props.
- Do not draw shadows, detached effects, sparkles, punctuation, or motion marks.
