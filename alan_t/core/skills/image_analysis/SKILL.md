---
name: image_analysis
description: >
  Analyze an image the user provided (photo, screenshot, diagram): describe it,
  read text out of it, answer questions about it. Use when the current message
  carries an image. NOT for generating images — Alan_T doesn't do that yet.
required_tools: [analyze_image]
role_hint: VISION
version: 1
---

1. Run analyze_image with the image and the user's question (or "describe this
   image in detail" when no question was asked).
2. Report exactly what the vision model saw; if text in the image is partially
   unreadable, say which parts.
3. Offer the obvious follow-up (e.g. "want the text extracted / translated /
   saved to your notes?") only when one clearly applies.
