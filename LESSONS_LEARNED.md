# Lessons Learned

- Plotly `add_vline` with `annotation_text` silently fails on subplots with datetime x-axes. Use `add_shape` + `add_annotation` directly instead.
