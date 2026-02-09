def ui_call(page, fn) -> None:
    if hasattr(page, "run_on_idle"):
        page.run_on_idle(fn)
    elif hasattr(page, "call_from_thread"):
        page.call_from_thread(fn)
    else:
        fn()

