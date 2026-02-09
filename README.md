# LLM-Desktop
Local AI desktop for GGUF models on Linux & SBCs (Radxa, Pi, etc.)
________________________________________________________________
<img width="1194" height="656" alt="Screenshot From 2026-02-08 11-29-22" src="https://github.com/user-attachments/assets/39fe49ab-0f7d-456c-b76d-408ca7e4d77b" />


This project built initially for the Baidu ERNIE hackathon, Oct 24-Nov23 2025.
This application is licensed under the MIT license

Designed as a free and open source alternative to apps like ChatGPT and Claude Desktop.

 *LLM-Desktop* 
 
 LLM-Desktop is a lightweight application to provide a nice GUI and toolset for running LLM models on SBCs or computers. It functions on ARM and AMD64 Linux currently, with plans to package it for windows. LLM-Desktop is designed for low cost, low power SBC systems, but also can run on a regular Linux PC.  LLM-Desktop has two built-in tools, internet search and file access.


*Getting started*

Internet search uses DuckDuckGo (via `ddgs`) and does not require any signup or API key.

You will need to download or build llamacpp for your architecture. You can find prebuilt binaries for many systems [here](https://github.com/ggml-org/llama.cpp/releases/). If you need to build from source visit llamacpp [here](https://github.com/ggml-org/llama.cpp) and follow instructions. Put the contents of the zip (or your build/bin directory if you built from source) into `chat/` inside the repo.

Then you need to get a model in GGUF format (Hugging Face, etc.) and place it into `models/` (or another directory you choose in the **Models** tab). We have tested with numerous models, all work fine, success at using tools is sketchy.

Run `./ed.sh` (mark it as executable if you get a permissions error). This launches the FastAPI backend and the Flet desktop UI. The model server is started when you select/switch a model in the UI (and the last model can auto-start on launch).

Once the app is loaded, use the **Models** tab to select and switch models.

*UI Notes*

- The desktop UI runs on Flet 0.24.1.
- On some Linux distros you may need `mpv-libs` installed (provides `libmpv.so.1`) for the window to launch.
- Use the paperclip to attach documents for context.

*About*

LLM-Desktop is comprised of 3 main parts. 
- llamcpp Provides inference via API
- fastAPI server Provides  tools, and device analytics
- Flet desktop application Provides the UI, control center, and document interface

  This software has been tested thouroughly on an AMD laptop and a Radxa Orion o6 ARM development board.

  
