extends Node2D

const CELL_WIDTH := 64
const CELL_HEIGHT := 64
const DISPLAY_SIZE := Vector2i(64, 64)
const WINDOW_SIZE := Vector2i(96, 96)
const SNAP_THRESHOLD := 72
const DRAG_DIRECTION_THRESHOLD := 8
const MOVE_INTERVAL := 0.04
const MOVE_SPEED := 720.0
const WINDOW_SNAP_THRESHOLD := 220
const FOLLOW_INTERVAL := 0.12
const BRIDGE_BASE_URL := "http://127.0.0.1:18992"

const STATE_ROWS := {
	"idle": {"row": 0, "count": 6, "durations": [0.28, 0.11, 0.11, 0.14, 0.14, 0.32]},
	"running-right": {"row": 1, "count": 8, "durations": [0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.22]},
	"running-left": {"row": 2, "count": 8, "durations": [0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.22]},
	"waving": {"row": 3, "count": 4, "durations": [0.14, 0.14, 0.14, 0.28]},
	"jumping": {"row": 4, "count": 5, "durations": [0.14, 0.14, 0.14, 0.14, 0.28]},
	"failed": {"row": 5, "count": 8, "durations": [0.14, 0.14, 0.14, 0.14, 0.14, 0.14, 0.14, 0.24]},
	"waiting": {"row": 6, "count": 6, "durations": [0.15, 0.15, 0.15, 0.15, 0.15, 0.26]},
	"running": {"row": 7, "count": 6, "durations": [0.12, 0.12, 0.12, 0.12, 0.12, 0.22]},
	"review": {"row": 8, "count": 6, "durations": [0.15, 0.15, 0.15, 0.15, 0.15, 0.28]},
}

const EDGE_HIDE_FILES := {
	"top": ["res://assets/edge-hide-64/bottom-edge-clean.png", "res://assets/edge-hide-64/bottom-edge-blink-clean.png", "res://assets/edge-hide-64/bottom-edge-clean.png"],
	"bottom": ["res://assets/edge-hide-64/top-edge-clean.png", "res://assets/edge-hide-64/top-edge-blink-clean.png", "res://assets/edge-hide-64/top-edge-clean.png"],
	"left": ["res://assets/edge-hide-64/left-edge-clean.png", "res://assets/edge-hide-64/left-edge-blink-clean.png", "res://assets/edge-hide-64/left-edge-clean.png"],
	"right": ["res://assets/edge-hide-64/right-edge-clean.png", "res://assets/edge-hide-64/right-edge-blink-clean.png", "res://assets/edge-hide-64/right-edge-clean.png"],
}

const EDGE_HIDE_DURATIONS := [1.4, 0.14, 1.4]

const WINDOW_DOCK_FILES := {
	"top": ["res://assets/window-dock-64/top-clean.png", "res://assets/window-dock-64/top-blink-clean.png", "res://assets/window-dock-64/top-clean.png"],
	"bottom": ["res://assets/window-dock-64/bottom-clean.png", "res://assets/window-dock-64/bottom-blink-clean.png", "res://assets/window-dock-64/bottom-clean.png"],
	"left": ["res://assets/window-dock-64/right-clean.png", "res://assets/window-dock-64/right-blink-clean.png", "res://assets/window-dock-64/right-clean.png"],
	"right": ["res://assets/window-dock-64/left-clean.png", "res://assets/window-dock-64/left-blink-clean.png", "res://assets/window-dock-64/left-clean.png"],
}

const WINDOW_DOCK_DURATIONS := [1.6, 0.14, 1.2]

const WINDOW_DOCK_ANCHOR_RATIOS := {
	"left": Vector2(1.0, 0.5),
	"right": Vector2(0.0, 0.5),
	"top": Vector2(0.5, 1.0),
	"bottom": Vector2(0.5, 0.0),
}

@onready var pet_sprite: Sprite2D = $PetSprite
@onready var http_request: HTTPRequest = $HttpRequest

var atlas_texture: Texture2D
var state_frames: Dictionary = {}
var edge_hide_frames: Dictionary = {}
var window_dock_frames: Dictionary = {}
var window_dock_anchors: Dictionary = {}
var window_dock_anchor_source: Dictionary = {}
var ordered_states: Array = []
var current_state := "idle"
var current_frame_index := 0
var current_mode := "state"
var current_edge := ""
var frame_timer := 0.0
var is_dragging := false
var drag_pointer_offset := Vector2i.ZERO
var drag_started := false
var drag_restore_state := "idle"
var drag_animation_state := ""
var screen_edge_attachment := ""
var screen_top_slot := -1
var pending_top_slot := -1
var top_hop_active := false
var top_hop_target_x := 0
var top_hop_completion_slot := -1
var window_attachment: Dictionary = {}
var follow_timer := 0.0
var pending_request_kind := ""


func _ready() -> void:
	randomize()
	_configure_window()
	http_request.request_completed.connect(_on_http_request_completed)
	atlas_texture = _load_texture("res://assets/hatch-pet/spritesheet-64.png")
	_build_state_frames()
	_build_edge_hide_frames()
	_build_window_dock_frames()
	ordered_states = STATE_ROWS.keys()
	_apply_state_frame("idle", 0)


func _process(delta: float) -> void:
	if top_hop_active:
		_process_top_hop(delta)

	if not window_attachment.is_empty() and not top_hop_active:
		follow_timer -= delta
		if follow_timer <= 0.0:
			follow_timer = FOLLOW_INTERVAL
			_request_window_follow()

	frame_timer -= delta
	if frame_timer > 0.0:
		return

	match current_mode:
		"state":
			var frames: Array = state_frames[current_state]
			current_frame_index = (current_frame_index + 1) % frames.size()
			_apply_frame_set(frames, current_frame_index)
		"edge-hide":
			var edge_frames: Array = edge_hide_frames.get(current_edge, [])
			if edge_frames.is_empty():
				return
			current_frame_index = (current_frame_index + 1) % edge_frames.size()
			_apply_frame_set(edge_frames, current_frame_index)
		"window-dock":
			var dock_frames: Array = window_dock_frames.get(current_edge, [])
			if dock_frames.is_empty():
				return
			current_frame_index = (current_frame_index + 1) % dock_frames.size()
			_apply_frame_set(dock_frames, current_frame_index)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if event.pressed:
			is_dragging = true
			drag_started = false
			drag_animation_state = ""
			var mouse_pos := DisplayServer.mouse_get_position()
			drag_pointer_offset = mouse_pos - DisplayServer.window_get_position()
			drag_restore_state = current_state
			window_attachment.clear()
			if not _is_screen_top_docked():
				_exit_special_modes()
		else:
			is_dragging = false
			if drag_started:
				_on_drag_finished()
			else:
				_handle_click()
		return

	if event is InputEventMouseMotion and is_dragging:
		var next_position := DisplayServer.mouse_get_position() - drag_pointer_offset
		DisplayServer.window_set_position(next_position)
		_update_drag_animation(event.relative)
		drag_started = true
		return

	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_1:
				set_state("idle")
			KEY_2:
				set_state("running-right")
			KEY_3:
				set_state("running-left")
			KEY_4:
				set_state("waving")
			KEY_5:
				set_state("jumping")
			KEY_6:
				set_state("failed")
			KEY_7:
				set_state("waiting")
			KEY_8:
				set_state("running")
			KEY_9:
				set_state("review")
			KEY_Q:
				set_edge_hide("left")
			KEY_W:
				set_edge_hide("top")
			KEY_E:
				set_edge_hide("right")
			KEY_R:
				set_edge_hide("bottom")
			KEY_A:
				set_window_dock("left")
			KEY_S:
				set_window_dock("top")
			KEY_D:
				set_window_dock("right")
			KEY_F:
				set_window_dock("bottom")
			KEY_ESCAPE:
				set_state("idle")


func set_state(state_name: String) -> void:
	if not state_frames.has(state_name):
		return
	screen_edge_attachment = ""
	screen_top_slot = -1
	pending_top_slot = -1
	current_mode = "state"
	current_edge = ""
	_apply_state_frame(state_name, 0)


func set_edge_hide(edge: String) -> void:
	if not edge_hide_frames.has(edge):
		return
	current_mode = "edge-hide"
	current_edge = edge
	current_frame_index = 0
	_apply_frame_set(edge_hide_frames[edge], 0)


func set_window_dock(edge: String) -> void:
	if not window_dock_frames.has(edge):
		return
	if current_mode == "window-dock" and current_edge == edge:
		return
	current_mode = "window-dock"
	current_edge = edge
	current_frame_index = 0
	_apply_frame_set(window_dock_frames[edge], 0)


func _exit_special_modes() -> void:
	if current_mode != "state":
		current_mode = "state"
		current_edge = ""
		current_frame_index = 0
		_apply_state_frame(current_state, 0)


func _update_drag_animation(relative_motion: Vector2) -> void:
	if absf(relative_motion.x) < DRAG_DIRECTION_THRESHOLD or absf(relative_motion.x) < absf(relative_motion.y):
		return
	var direction_state := "running-right" if relative_motion.x > 0.0 else "running-left"
	if direction_state == drag_animation_state:
		return
	drag_animation_state = direction_state
	set_state(direction_state)


func _on_drag_finished() -> void:
	if not drag_started:
		return
	drag_started = false
	drag_animation_state = ""
	print("[godot_pet] drag finished pos=%s pointer=%s restore_state=%s" % [
		DisplayServer.window_get_position(),
		DisplayServer.mouse_get_position(),
		drag_restore_state,
	])
	_snap_to_screen_edge()


func _handle_click() -> void:
	if _is_screen_top_docked():
		_handle_top_dock_click()
		return
	_cycle_state()


func _snap_to_screen_edge() -> void:
	var screen := DisplayServer.window_get_current_screen()
	var usable_rect: Rect2i = DisplayServer.screen_get_usable_rect(screen)
	var window_pos := DisplayServer.window_get_position()
	var mouse_pos := DisplayServer.mouse_get_position()
	var window_size := get_window().size
	var max_x := usable_rect.position.x + usable_rect.size.x - window_size.x
	var max_y := usable_rect.position.y + usable_rect.size.y - window_size.y
	var clamped_x := clampi(window_pos.x, usable_rect.position.x, max_x)
	var clamped_y := clampi(window_pos.y, usable_rect.position.y, max_y)
	var distances := {
		"left": absi(mouse_pos.x - usable_rect.position.x),
		"right": absi(usable_rect.position.x + usable_rect.size.x - mouse_pos.x),
		"top": absi(mouse_pos.y - usable_rect.position.y),
		"bottom": absi(usable_rect.position.y + usable_rect.size.y - mouse_pos.y),
	}
	var nearest_edge: String = "left"
	var nearest_distance: int = distances[nearest_edge]
	for edge in distances.keys():
		if distances[edge] < nearest_distance:
			nearest_edge = edge
			nearest_distance = distances[edge]

	if nearest_distance <= SNAP_THRESHOLD:
		match nearest_edge:
			"left":
				clamped_x = usable_rect.position.x
				screen_edge_attachment = "left"
				screen_top_slot = -1
				pending_top_slot = -1
			"right":
				clamped_x = max_x
				screen_edge_attachment = "right"
				screen_top_slot = -1
				pending_top_slot = -1
			"top":
				clamped_y = usable_rect.position.y
				var slot_result := _nearest_top_slot(clamped_x, usable_rect)
				screen_top_slot = slot_result[0]
				clamped_x = slot_result[1]
				screen_edge_attachment = "top"
			"bottom":
				clamped_y = max_y
				screen_edge_attachment = "bottom"
				screen_top_slot = -1
				pending_top_slot = -1
		DisplayServer.window_set_position(Vector2i(clamped_x, clamped_y))
		window_attachment.clear()
		print("[godot_pet] snapped to screen edge=%s pos=%s slot=%s" % [
			nearest_edge,
			Vector2i(clamped_x, clamped_y),
			screen_top_slot,
		])
		set_edge_hide(nearest_edge)
		return

	screen_edge_attachment = ""
	screen_top_slot = -1
	pending_top_slot = -1
	print("[godot_pet] screen edge skipped nearest=%s distance=%s threshold=%s -> requesting window attachment" % [
		nearest_edge,
		nearest_distance,
		SNAP_THRESHOLD,
	])
	_request_window_attachment()


func _top_slot_positions(usable_rect: Rect2i) -> Array:
	var max_x := usable_rect.position.x + usable_rect.size.x - WINDOW_SIZE.x
	var left_x := usable_rect.position.x
	var center_x := left_x + maxi(0, (max_x - left_x) / 2)
	return [left_x, center_x, max_x]


func _nearest_top_slot(current_x: int, usable_rect: Rect2i) -> Array:
	var positions: Array = _top_slot_positions(usable_rect)
	var slot_index := 0
	var best_distance := absi(current_x - int(positions[0]))
	for index in range(1, positions.size()):
		var distance := absi(current_x - int(positions[index]))
		if distance < best_distance:
			best_distance = distance
			slot_index = index
	return [slot_index, int(positions[slot_index])]


func _is_screen_top_docked() -> bool:
	return screen_edge_attachment == "top" and screen_top_slot >= 0


func _plan_top_slot_transition(current_slot: int) -> Array:
	if current_slot == 0:
		return [1, 2]
	if current_slot == 2:
		return [1, 0]
	if pending_top_slot >= 0:
		return [pending_top_slot, -1]
	var next_slot: int = [0, 2][randi() % 2]
	return [next_slot, -1]


func _handle_top_dock_click() -> void:
	if top_hop_active:
		return
	var screen := DisplayServer.window_get_current_screen()
	var usable_rect: Rect2i = DisplayServer.screen_get_usable_rect(screen)
	var current_slot := screen_top_slot
	if current_slot < 0:
		var slot_result := _nearest_top_slot(DisplayServer.window_get_position().x, usable_rect)
		current_slot = slot_result[0]
	var transition := _plan_top_slot_transition(current_slot)
	var target_slot: int = transition[0]
	pending_top_slot = transition[1]
	var positions: Array = _top_slot_positions(usable_rect)
	top_hop_target_x = int(positions[target_slot])
	top_hop_completion_slot = target_slot
	top_hop_active = true
	set_state("running-right" if top_hop_target_x > DisplayServer.window_get_position().x else "running-left")


func _process_top_hop(delta: float) -> void:
	var current_pos := DisplayServer.window_get_position()
	var delta_x := top_hop_target_x - current_pos.x
	if absi(delta_x) <= 1:
		DisplayServer.window_set_position(Vector2i(top_hop_target_x, current_pos.y))
		top_hop_active = false
		screen_edge_attachment = "top"
		screen_top_slot = top_hop_completion_slot
		top_hop_completion_slot = -1
		set_edge_hide("top")
		return
	var step := maxi(1, roundi(MOVE_SPEED * delta))
	var next_x := current_pos.x + clampi(delta_x, -step, step)
	DisplayServer.window_set_position(Vector2i(next_x, current_pos.y))


func _cycle_state() -> void:
	var current_index := ordered_states.find(current_state)
	var next_index := (current_index + 1) % ordered_states.size()
	set_state(ordered_states[next_index])


func _request_window_attachment() -> void:
	if pending_request_kind != "" or top_hop_active:
		return
	var pos := DisplayServer.window_get_position()
	var pointer := DisplayServer.mouse_get_position()
	var url := "%s/nearest?x=%d&y=%d&width=%d&height=%d&threshold=%d" % [
		BRIDGE_BASE_URL,
		pos.x,
		pos.y,
		WINDOW_SIZE.x,
		WINDOW_SIZE.y,
		WINDOW_SNAP_THRESHOLD,
	]
	url += "&pointer_x=%d&pointer_y=%d" % [pointer.x, pointer.y]
	url += "&exclude_pid=%d" % [OS.get_process_id()]
	url += _anchor_query()
	pending_request_kind = "nearest"
	print("[godot_pet] request nearest url=%s" % url)
	http_request.request(url)


func _request_window_follow() -> void:
	if pending_request_kind != "" or window_attachment.is_empty():
		return
	var pos := DisplayServer.window_get_position()
	var top_slot_value = window_attachment.get("top_slot", null)
	var top_slot_param := ""
	if top_slot_value != null:
		top_slot_param = str(int(top_slot_value))
	var url := "%s/follow?hwnd=%d&edge=%s&offset=%d&x=%d&y=%d&width=%d&height=%d&top_slot=%s" % [
		BRIDGE_BASE_URL,
		int(window_attachment["hwnd"]),
		String(window_attachment["edge"]),
		int(window_attachment["offset"]),
		pos.x,
		pos.y,
		WINDOW_SIZE.x,
		WINDOW_SIZE.y,
		top_slot_param,
	]
	url += "&exclude_pid=%d" % [OS.get_process_id()]
	url += _anchor_query()
	pending_request_kind = "follow"
	print("[godot_pet] request follow url=%s attachment=%s" % [url, window_attachment])
	http_request.request(url)


func _on_http_request_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var request_kind := pending_request_kind
	pending_request_kind = ""
	print("[godot_pet] response kind=%s result=%s code=%s body=%s" % [
		request_kind,
		result,
		response_code,
		body.get_string_from_utf8(),
	])
	if response_code != 200:
		if request_kind == "nearest":
			set_state(drag_restore_state)
		elif request_kind == "follow":
			window_attachment.clear()
			set_state("idle")
		return

	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if typeof(parsed) != TYPE_DICTIONARY:
		return
	var payload: Dictionary = parsed

	if request_kind == "nearest":
		if not payload.get("matched", false):
			if int(payload.get("bridge_version", 0)) < 2:
				print("[godot_pet] nearest response looks like an old bridge version; restart window_bridge.py")
			var nearest = payload.get("nearest", {})
			var nearest_title := "<unknown>"
			var nearest_edge := "<unknown>"
			var nearest_distance := -1
			var nearest_pointer_inside := false
			var nearest_overlap := 0
			var rect_left := -1
			var rect_top := -1
			var rect_right := -1
			var rect_bottom := -1
			if typeof(nearest) == TYPE_DICTIONARY:
				nearest_title = String(nearest.get("title", "<unknown>"))
				nearest_edge = String(nearest.get("edge", "<unknown>"))
				nearest_distance = int(nearest.get("distance", -1))
				nearest_pointer_inside = bool(nearest.get("pointer_inside", false))
				nearest_overlap = int(nearest.get("overlap", 0))
				var rect = nearest.get("rect", {})
				if typeof(rect) == TYPE_DICTIONARY:
					rect_left = int(rect.get("left", -1))
					rect_top = int(rect.get("top", -1))
					rect_right = int(rect.get("right", -1))
					rect_bottom = int(rect.get("bottom", -1))
			print("[godot_pet] nearest no match bridge_version=%s candidates=%s nearest_title=%s nearest_edge=%s nearest_distance=%s pointer_inside=%s overlap=%s -> restore %s" % [
				payload.get("bridge_version", 0),
				payload.get("candidates", -1),
				nearest_title,
				nearest_edge,
				nearest_distance,
				nearest_pointer_inside,
				nearest_overlap,
				drag_restore_state,
			])
			print("[godot_pet] nearest rect tl=(%s,%s) tr=(%s,%s) br=(%s,%s) bl=(%s,%s)" % [
				rect_left,
				rect_top,
				rect_right,
				rect_top,
				rect_right,
				rect_bottom,
				rect_left,
				rect_bottom,
			])
			print("[godot_pet] self_rect=%s window_pos=%s mouse=%s" % [
				payload.get("self_rect", null),
				DisplayServer.window_get_position(),
				DisplayServer.mouse_get_position(),
			])
			set_state(drag_restore_state)
			return
		window_attachment = payload["attachment"]
		screen_edge_attachment = ""
		screen_top_slot = -1
		pending_top_slot = -1
		var target: Dictionary = window_attachment["target"]
		DisplayServer.window_set_position(Vector2i(int(target["x"]), int(target["y"])))
		print("[godot_pet] attached to window edge=%s hwnd=%s target=%s" % [
			String(window_attachment["edge"]),
			int(window_attachment["hwnd"]),
			target,
		])
		print("[godot_pet] attached title=%s" % [String(window_attachment.get("title", "<unknown>"))])
		print("[godot_pet] attached physical_target=%s logical_rect=%s physical_rect=%s" % [
			window_attachment.get("physical_target", {}),
			payload.get("logical_rect", {}),
			payload.get("physical_rect", {}),
		])
		print("[godot_pet] attached physical_anchors=%s" % [window_attachment.get("physical_anchors", {})])
		var attached_rect = window_attachment.get("rect", {})
		if typeof(attached_rect) == TYPE_DICTIONARY:
			print("[godot_pet] attached rect left=%s top=%s right=%s bottom=%s edge_distances=%s" % [
				attached_rect.get("left", "?"),
				attached_rect.get("top", "?"),
				attached_rect.get("right", "?"),
				attached_rect.get("bottom", "?"),
				window_attachment.get("edge_distances", {}),
			])
		set_window_dock(String(window_attachment["edge"]))
		follow_timer = FOLLOW_INTERVAL
		return

	if request_kind == "follow":
		if not payload.get("available", false):
			print("[godot_pet] follow unavailable -> detach")
			window_attachment.clear()
			set_state("idle")
			return
		var target: Dictionary = payload["target"]
		DisplayServer.window_set_position(Vector2i(int(target["x"]), int(target["y"])))
		print("[godot_pet] follow moved to target=%s edge=%s" % [
			target,
			String(window_attachment["edge"]),
		])
		set_window_dock(String(window_attachment["edge"]))


func _apply_state_frame(state_name: String, frame_index: int) -> void:
	current_state = state_name
	current_frame_index = frame_index
	_apply_frame_set(state_frames[state_name], frame_index)


func _apply_frame_set(frames: Array, frame_index: int) -> void:
	var frame: Dictionary = frames[frame_index]
	pet_sprite.texture = frame["texture"]
	pet_sprite.offset = frame["offset"]
	pet_sprite.scale = frame["scale"]
	pet_sprite.position = frame["position"]
	frame_timer = frame["duration"]


func _build_state_frames() -> void:
	for state_name in STATE_ROWS.keys():
		var spec: Dictionary = STATE_ROWS[state_name]
		var frames: Array = []
		for column in range(spec["count"]):
			var region := Rect2i(column * CELL_WIDTH, spec["row"] * CELL_HEIGHT, CELL_WIDTH, CELL_HEIGHT)
			var atlas_frame := AtlasTexture.new()
			atlas_frame.atlas = atlas_texture
			atlas_frame.region = region
			frames.append({
				"texture": atlas_frame,
				"duration": spec["durations"][column],
				"offset": Vector2.ZERO,
				"scale": _fit_scale(Vector2(CELL_WIDTH, CELL_HEIGHT)),
				"position": _mode_position("state", Vector2(CELL_WIDTH, CELL_HEIGHT), ""),
			})
		state_frames[state_name] = frames


func _build_edge_hide_frames() -> void:
	for edge in EDGE_HIDE_FILES.keys():
		var frames: Array = []
		for idx in range(EDGE_HIDE_FILES[edge].size()):
			var trimmed: Dictionary = _load_trimmed_texture(EDGE_HIDE_FILES[edge][idx])
			var texture: Texture2D = trimmed["texture"]
			var size: Vector2 = trimmed["size"]
			frames.append({
				"texture": texture,
				"duration": EDGE_HIDE_DURATIONS[idx],
				"offset": _texture_center_offset(texture),
				"scale": _fit_scale(size),
				"position": _mode_position("edge-hide", size, edge),
			})
		edge_hide_frames[edge] = frames


func _build_window_dock_frames() -> void:
	for edge in WINDOW_DOCK_FILES.keys():
		var first_path: String = WINDOW_DOCK_FILES[edge][0]
		var trimmed: Dictionary = _load_trimmed_texture(first_path)
		var texture: Texture2D = trimmed["texture"]
		var size: Vector2 = trimmed["size"]
		var anchor_ratio: Vector2 = WINDOW_DOCK_ANCHOR_RATIOS[edge]
		var source_anchor := Vector2i(
			roundi(size.x * anchor_ratio.x),
			roundi(size.y * anchor_ratio.y)
		)
		var scale_vec := _fit_scale(size)
		var position := _mode_position("window-dock", size, edge)
		var window_anchor := position + (Vector2(source_anchor) - (size / 2.0)) * scale_vec
		window_dock_anchor_source[edge] = source_anchor
		window_dock_anchors[edge] = Vector2i(roundi(window_anchor.x), roundi(window_anchor.y))
		var frames: Array = []
		for idx in range(WINDOW_DOCK_FILES[edge].size()):
			var frame_trimmed: Dictionary = _load_trimmed_texture(WINDOW_DOCK_FILES[edge][idx])
			var frame_texture: Texture2D = frame_trimmed["texture"]
			frames.append({
				"texture": frame_texture,
				"duration": WINDOW_DOCK_DURATIONS[idx],
				"offset": _texture_center_offset(frame_texture),
				"scale": scale_vec,
				"position": position,
			})
		window_dock_frames[edge] = frames


func _texture_center_offset(texture: Texture2D) -> Vector2:
	return Vector2.ZERO


func _configure_window() -> void:
	get_tree().root.transparent_bg = true
	get_viewport().transparent_bg = true
	get_window().borderless = true
	get_window().transparent = true
	get_window().transparent_bg = true
	get_window().always_on_top = true
	get_window().size = WINDOW_SIZE
	RenderingServer.set_default_clear_color(Color(0, 0, 0, 0))
	DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_BORDERLESS, true)
	DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_TRANSPARENT, true)
	DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_ALWAYS_ON_TOP, true)


func _load_trimmed_texture(path: String) -> Dictionary:
	var image := Image.new()
	var error := image.load(path)
	if error != OK:
		push_error("Failed to load texture: %s (error=%s)" % [path, error])
		return {"texture": null, "size": Vector2.ZERO}
	var used_rect: Rect2i = image.get_used_rect()
	if used_rect.size.x > 0 and used_rect.size.y > 0:
		image = image.get_region(used_rect)
	return {
		"texture": ImageTexture.create_from_image(image),
		"size": Vector2(image.get_width(), image.get_height()),
	}


func _load_texture(path: String) -> Texture2D:
	var image := Image.new()
	var error := image.load(path)
	if error != OK:
		push_error("Failed to load texture: %s (error=%s)" % [path, error])
		return null
	return ImageTexture.create_from_image(image)


func _fit_scale(size: Vector2) -> Vector2:
	var scale_factor: float = min(
		float(DISPLAY_SIZE.x) / float(size.x),
		float(DISPLAY_SIZE.y) / float(size.y)
	)
	return Vector2.ONE * scale_factor


func _mode_position(mode: String, size: Vector2, edge: String) -> Vector2:
	var scale_vec: Vector2 = _fit_scale(size)
	var drawn_size := Vector2(size.x * scale_vec.x, size.y * scale_vec.y)
	var center := Vector2(WINDOW_SIZE.x / 2.0, WINDOW_SIZE.y / 2.0)
	if mode == "state":
		return center
	var half_w := drawn_size.x / 2.0
	var half_h := drawn_size.y / 2.0
	match edge:
		"left":
			return Vector2(half_w, center.y)
		"right":
			return Vector2(WINDOW_SIZE.x - half_w, center.y)
		"top":
			return Vector2(center.x, half_h)
		"bottom":
			return Vector2(center.x, WINDOW_SIZE.y - half_h)
		_:
			return center


func _anchor_query() -> String:
	var left_anchor: Vector2i = window_dock_anchors.get("left", Vector2i(WINDOW_SIZE.x, WINDOW_SIZE.y / 2))
	var right_anchor: Vector2i = window_dock_anchors.get("right", Vector2i(0, WINDOW_SIZE.y / 2))
	var top_anchor: Vector2i = window_dock_anchors.get("top", Vector2i(WINDOW_SIZE.x / 2, WINDOW_SIZE.y))
	var bottom_anchor: Vector2i = window_dock_anchors.get("bottom", Vector2i(WINDOW_SIZE.x / 2, 0))
	return "&anchor_left_x=%d&anchor_left_y=%d&anchor_right_x=%d&anchor_right_y=%d&anchor_top_x=%d&anchor_top_y=%d&anchor_bottom_x=%d&anchor_bottom_y=%d" % [
		left_anchor.x,
		left_anchor.y,
		right_anchor.x,
		right_anchor.y,
		top_anchor.x,
		top_anchor.y,
		bottom_anchor.x,
		bottom_anchor.y,
	]
