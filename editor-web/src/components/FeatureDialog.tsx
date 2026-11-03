import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpDown, Box, Combine, Crosshair, MousePointerClick, Scissors, SquarePlus, type LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { OperationChooser } from "@/components/OperationChooser";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectLabel, SelectGroup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { plainDescription, plainLabel } from "@/lib/commands";
import { OPERATION_SLOT, TARGET_SLOT, formDefaults, type CombineState, operationOptions, targetDisplay, visibleSlots } from "@/lib/combine";
import { defaultExtrudeDistance, profileSummary, type SketchInfo } from "@/lib/sketch-scene";
import type { SketchSolved } from "@/lib/useSketchShapes";
import { frameNormal, normalizePlane, dot, type Vec3 } from "@/lib/sketch-plane";
import { directionVector } from "@/scene/sketch-layer";
import {
  CellFailure,
  FLIP_NORMAL,
  FRIENDLY_NAMES,
  bodyChoices,
  directionForProfile,
  directionOptions,
  resolveDirection,
  findProfile,
  filterSelection,
  formToValues,
  holeFromFace,
  initialForm,
  profilePlaneLabel,
  isDescribed,
  pickedPayload,
  suggestName,
  validateName,
  type FeatureCommand,
  type FeatureRow,
  type FeatureState,
  type PickedItem,
  type RawForm,
  type Slot,
  type SlotOption,
  type Spec,
} from "@/lib/features";
import type { SelectionItem } from "@/lib/selection";
import type { SelectionMode } from "@/scene/Viewport";

/** The icon of each way a new solid meets the body (colour stays reserved for meaning, so the icons carry no ink). */
const OPERATION_ICONS: Record<string, LucideIcon> = { join: SquarePlus, cut: Scissors, intersect: Combine, new: Box };

/** `prefill` sets starting values of slots (a sketch to extrude, a distance); `fromFace` fills a hole from the selected face. */
export type DialogRequest = { spec: Spec; edit?: FeatureRow; prefill?: Record<string, unknown>; fromFace?: boolean };

/** What the form knows of the notebook's sketches: who they are, their solved shapes, and the one selected in the viewport. */
export type DialogSketches = {
  infos: readonly SketchInfo[];
  shapes: ReadonlyMap<string, SketchSolved>;
  picked: string | null;
  /** The arrow the viewport draws for the push the form describes (null: none). */
  onPreview: (arrow: { sketch: string; direction: Vec3; distance: number } | null) => void;
};

/** The form of one operation, generated from its spec.  A docked card, not a modal: the viewport stays live. */
export function FeatureDialog({
  request,
  state,
  selection,
  sketches,
  onSelectionMode,
  onSubmit,
  onClose,
}: {
  request: DialogRequest | null;
  state: FeatureState;
  selection: SelectionItem[];
  sketches: DialogSketches;
  onSelectionMode: (mode: SelectionMode) => void;
  /** Runs the command; rejects with the server's message, shown inline. */
  onSubmit: (command: FeatureCommand) => Promise<void>;
  onClose: () => void;
}) {
  return (
    <Dialog open={request !== null} modal={false} onOpenChange={(open) => !open && onClose()}>
      {request && (
        <FeatureForm
          key={`${request.spec.id}:${request.edit?.cell ?? "new"}`}
          request={request}
          state={state}
          selection={selection}
          sketches={sketches}
          onSelectionMode={onSelectionMode}
          onSubmit={onSubmit}
          onClose={onClose}
        />
      )}
    </Dialog>
  );
}

function FeatureForm({
  request,
  state,
  selection,
  sketches,
  onSelectionMode,
  onSubmit,
  onClose,
}: {
  request: DialogRequest;
  state: FeatureState;
  selection: SelectionItem[];
  sketches: DialogSketches;
  onSelectionMode: (mode: SelectionMode) => void;
  onSubmit: (command: FeatureCommand) => Promise<void>;
  onClose: () => void;
}) {
  const { spec, edit } = request;
  const editing = Boolean(edit);
  const profileSlotOf = spec.slots.find((slot) => slot.kind === "profile");
  const hasDirection = spec.slots.some((slot) => slot.name === "direction");
  const serverFlips = Boolean(spec.slots.find((slot) => slot.name === "direction")?.options?.some((option) => option.value === FLIP_NORMAL));
  const [form, setForm] = useState<RawForm>(() => {
    // A new feature takes the sketch selected in the viewport as its profile (the prefill of a command wins).
    const chosen = !edit && profileSlotOf && sketches.picked && findProfile(state, sketches.picked) ? { [profileSlotOf.name]: sketches.picked } : {};
    const base = initialForm(spec, formDefaults(spec, state.defaults[spec.id] ?? {}, editing), { ...(edit?.gui?.values ?? {}), ...chosen, ...(request.prefill ?? {}) });
    const named = profileSlotOf && typeof base[profileSlotOf.name] === "string" ? (base[profileSlotOf.name] as string) : null;
    // A new push takes about a quarter of the sketch's largest extent as its distance (unless the command said one).
    const sizeSlot = spec.slots.find((slot) => slot.name === "distance" || slot.name === "depth");
    const shape = named ? sketches.shapes.get(named)?.shape : undefined;
    const sized: RawForm = !edit && sizeSlot && shape?.extent && !(request.prefill && sizeSlot.name in request.prefill) ? { ...base, [sizeSlot.name]: String(defaultExtrudeDistance(shape, Number(base[sizeSlot.name]) || 10)) } : base;
    // A new feature on a sketch pushes along that sketch's plane normal.
    const normal = !edit && named ? directionForProfile(state, named) : null;
    if (!(normal && hasDirection)) return sized;
    // A cut goes into the material: for a sketch drawn on a face (a frame, its normal pointing out) that is against the normal.
    const profile = named ? findProfile(state, named) : undefined;
    const into = (spec.id === "cut_sketch" || base.operation === "cut") && profile && profilePlaneLabel(profile) === "face";
    return { ...sized, direction: into ? FLIP_NORMAL : normal };
  });
  const [name, setName] = useState(edit?.slug ?? "");
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  // A new feature whose cell failed exists already: the next submit edits it instead of adding a second one.
  const [created, setCreated] = useState<string | null>(null);

  // Picks present when the form opened: in edit mode only a different pick replaces the recipe.
  const [initialKeys] = useState(() => new Set(selection.map((item) => item.key)));
  const selectSlots = spec.slots.filter((slot) => slot.kind === "select");
  const picksOf = (slot: Slot) => filterSelection(selection, slot.entity ?? "face");
  const replaced = (slot: Slot) => {
    const keys = picksOf(slot).map((item) => item.key);
    if (!keys.length) return false;
    return !editing || keys.length !== initialKeys.size || keys.some((key) => !initialKeys.has(key));
  };

  // The sketch field is armed: a click on a sketch in the viewport or the tree fills it (until the person turns it off).
  const [armed, setArmed] = useState(() => Boolean(profileSlotOf) && !(request.prefill && profileSlotOf && request.prefill[profileSlotOf.name]));

  // The viewport picks what the form asks for while it is open, and goes back after.
  const wanted = (selectSlots[0]?.entity ?? (spec.id === "hole" ? "face" : profileSlotOf && armed ? "sketch" : null)) as SelectionMode | null;
  useEffect(() => {
    if (wanted) onSelectionMode(wanted);
  }, [wanted, onSelectionMode]);

  const set = (slot: string, value: RawForm[string]) => {
    setForm((previous) => ({ ...previous, [slot]: value }));
    setServerError(null);
  };

  const { values: formValues, errors: formErrors } = useMemo(() => formToValues(spec, form), [spec, form]);
  const profileSlotName = spec.slots.find((slot) => slot.kind === "profile")?.name;
  const profileRaw = profileSlotName ? form[profileSlotName] : undefined;
  const profileName = typeof profileRaw === "string" ? profileRaw : null;
  const values = useMemo(
    () => (typeof formValues.direction === "string" ? { ...formValues, direction: resolveDirection(formValues.direction, state, profileName, serverFlips) } : formValues),
    [formValues, state, profileName, serverFlips],
  );
  const errors = formErrors;

  /** The direction a profile starts with: its normal, or into the material for a cut on a face. */
  const startDirection = (profile: string, operation: unknown): string | null => {
    const normal = directionForProfile(state, profile);
    const found = findProfile(state, profile);
    return normal && (spec.id === "cut_sketch" || operation === "cut") && found && profilePlaneLabel(found) === "face" ? FLIP_NORMAL : normal;
  };
  const applyProfile = (profile: string) => {
    const direction = startDirection(profile, form[OPERATION_SLOT]);
    setForm((previous) => ({ ...previous, ...(profileSlotOf ? { [profileSlotOf.name]: profile } : {}), ...(direction && hasDirection ? { direction } : {}) }));
    setServerError(null);
  };

  /** Choosing Cut for a sketch drawn on a face aims the push into the material (and back out for another operation), unless the
   * person already turned it: the direction is only changed while it still is the one the previous choice started with. */
  const onOperation = (operation: string) => {
    const before = form[OPERATION_SLOT];
    setForm((previous) => {
      const next: RawForm = { ...previous, [OPERATION_SLOT]: operation };
      if (!(profileName && hasDirection)) return next;
      const was = startDirection(profileName, before);
      if (previous.direction === was) {
        const now = startDirection(profileName, operation);
        if (now) next.direction = now;
      }
      return next;
    });
    setServerError(null);
  };

  // A sketch picked in the viewport or the tree fills the armed profile field.
  const lastPicked = useRef(sketches.picked);
  useEffect(() => {
    if (sketches.picked === lastPicked.current) return;
    lastPicked.current = sketches.picked;
    if (armed && sketches.picked && profileSlotOf && findProfile(state, sketches.picked)) applyProfile(sketches.picked);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sketches.picked]);

  // The viewport shows which way the push goes, from the sketch, as an arrow (and says nothing once the form is gone).
  const previewRef = useRef(sketches.onPreview);
  previewRef.current = sketches.onPreview;
  const directionText = typeof values.direction === "string" ? values.direction : null;
  const pushed = typeof values.distance === "number" ? values.distance : typeof values.depth === "number" ? values.depth : null;
  useEffect(() => {
    const found = profileName ? findProfile(state, profileName) : undefined;
    const vector = found && directionText ? directionVector(directionText, normalizePlane(found.plane)) : null;
    previewRef.current(found && vector ? { sketch: found.name, direction: vector, distance: Math.abs(pushed ?? 10) } : null);
  }, [profileName, directionText, pushed, state]);
  useEffect(() => () => previewRef.current(null), []);

  /** Which way the push goes relative to the sketch's own normal (null without a sketch), and whether it can be flipped. */
  const flip = useMemo(() => {
    const found = profileName ? findProfile(state, profileName) : undefined;
    if (!found || !hasDirection || !directionText) return null;
    const plane = normalizePlane(found.plane);
    const normal = found.normal_vec ?? frameNormal(plane as never as { origin: Vec3; x_axis: Vec3; y_axis: Vec3 });
    const vector = directionVector(directionText, plane);
    const against = vector ? dot(vector, normal as Vec3) < 0 : false;
    const axis = /^[+-][xyz]$/.test(found.normal) ? found.normal : "normal";
    return { against, axis, can: directionOptions(spec.slots.find((slot) => slot.name === "direction")?.options ?? [], state, profileName).some((option) => option.value === FLIP_NORMAL) };
  }, [profileName, directionText, state, hasDirection, spec]);
  const onFlip = () => set("direction", flip?.against ? "normal" : FLIP_NORMAL);

  const nameError = editing || created ? null : validateName(name, state.taken);
  const suggested = suggestName(spec.id, state.taken);

  const selectionErrors: Record<string, string> = {};
  const selections: Record<string, PickedItem[]> = {};
  for (const slot of selectSlots) {
    const picks = picksOf(slot);
    if (replaced(slot)) {
      if (picks.some((item) => !isDescribed(item))) selectionErrors[slot.name] = "details of the picked items are still loading";
      else selections[slot.name] = picks.map(pickedPayload);
    } else if (!editing && !slot.optional) selectionErrors[slot.name] = `pick ${slot.entity === "edge" ? "edges" : "faces"} in the viewport`;
  }

  const allErrors = { ...errors, ...selectionErrors };
  const invalid = Object.keys(allErrors).length > 0 || nameError !== null;

  const submit = async () => {
    setTouched(true);
    if (invalid || busy) return;
    setBusy(true);
    setServerError(null);
    const withSelections = Object.keys(selections).length ? { selections } : {};
    const command: FeatureCommand = edit
      ? { op: "edit", cell: edit.cell, values, ...withSelections }
      : created
        ? { op: "edit", cell: created, values, ...withSelections }
        : { op: "add", spec: spec.id, ...(name.trim() ? { name: name.trim() } : FRIENDLY_NAMES.has(spec.id) ? { name: suggested } : {}), values, ...withSelections };
    try {
      await onSubmit(command);
    } catch (error) {
      if (error instanceof CellFailure && !edit) setCreated(error.cell);
      setServerError(error instanceof Error ? error.message : String(error));
      setBusy(false);
    }
  };

  const fillFromFace = () => {
    const faces = filterSelection(selection, "face");
    if (faces.length !== 1) {
      setNote("Pick exactly one face in the viewport first.");
      return;
    }
    const face = faces[0];
    if (!isDescribed(face)) {
      setNote("The face details are still loading; try again in a moment.");
      return;
    }
    const { point, direction } = holeFromFace(face);
    if (!point) {
      setNote("This face has no centroid; type the start point.");
      return;
    }
    setForm((previous) => ({
      ...previous,
      position: point.map((c) => String(Math.round(c * 1e4) / 1e4)),
      ...(direction ? { direction } : {}),
    }));
    setNote(
      direction
        ? `Start point set from the face centroid, direction ${direction} (into the material).`
        : "Start point set from the face centroid. The face reports no normal: check the direction.",
    );
    setServerError(null);
  };

  // A hole opened from a selected face takes its start point and direction from it as soon as the face is described.
  const faceUsed = useRef(false);
  useEffect(() => {
    if (!request.fromFace || faceUsed.current) return;
    const faces = filterSelection(selection, "face");
    if (faces.length === 1 && isDescribed(faces[0])) {
      faceUsed.current = true;
      fillFromFace();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection]);

  // The feature the combine controls describe: the one being edited, or the one this form just created and whose cell failed
  // (its product is then an open body, but not one it combines with).
  const shaped = edit ?? (created ? state.features.find((row) => row.cell === created) : undefined);
  // A new solid is described against the bodies open when the form opened: once it is added the state changes before the form
  // closes, and "Combined with" must not flip to the solid just made.
  const [openAtStart] = useState(() => state.open);
  const combine = edit || created ? state : { open: openAtStart };
  const own = new Set(edit?.makes ?? []);
  const bodies = bodyChoices(state).filter((body) => !own.has(body.name));

  return (
    <DialogContent
      aria-describedby={undefined}
      onOpenAutoFocus={(event) => event.preventDefault()}
      onKeyDown={(event) => {
        if (event.key === "Enter" && !(event.target instanceof HTMLTextAreaElement) && !(event.target instanceof HTMLButtonElement)) {
          event.preventDefault();
          void submit();
        }
      }}
    >
      <DialogHeader>
        <DialogTitle>
          {editing ? "Edit" : "Add"} {plainLabel(spec.id, spec.label).toLowerCase()}
        </DialogTitle>
        <DialogDescription>{plainDescription(spec.id, spec.description)}</DialogDescription>
      </DialogHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-3 py-3">
        <Field label="Name" error={touched ? nameError : null} help={editing ? "A feature keeps its name." : undefined}>
          <Input
            value={editing ? (edit?.slug ?? "") : name}
            disabled={editing}
            placeholder={suggested}
            aria-invalid={touched && nameError !== null}
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        {visibleSlots(spec, form).map((slot) => slot.name === TARGET_SLOT && spec.combinable && targetDisplay(combine, shaped, String(form[slot.name] ?? "")).kind === "hidden" ? null : (
          <Field key={slot.name} label={combineLine(spec, slot, form, combine, shaped) ? "" : slot.label} unit={slot.kind === "point" ? slot.unit : undefined} help={(spec.id === "hole" && slot.name === "position" && note) || (spec.combinable && (slot.name === OPERATION_SLOT || slot.name === TARGET_SLOT)) ? undefined : slot.help} error={touched ? (allErrors[slot.name] ?? null) : null}>
            <SlotWidget
              slot={slot}
              form={form}
              set={slot.name === OPERATION_SLOT && spec.combinable ? (_slot, value) => onOperation(String(value)) : set}
              edit={shaped}
              combine={combine}
              invalid={touched && Boolean(errors[slot.name])}
              bodies={bodies}
              selection={selection}
              state={state}
              onProfile={applyProfile}
              sketches={sketches}
              armed={armed}
              onArm={setArmed}
              flip={slot.name === "direction" && slot.kind === "enum" ? flip : null}
              onFlip={onFlip}
              kept={editing && !replaced(slot)}
              picks={slot.kind === "select" ? picksOf(slot).length : 0}
              options={slot.name === "direction" && slot.kind === "enum" ? directionOptions(slot.options ?? [], state, profileName) : undefined}
            />
            {spec.id === "hole" && slot.name === "position" && (
              <div className="mt-1 flex flex-col gap-1">
                <Button type="button" size="sm" variant="outline" onClick={fillFromFace}>
                  <MousePointerClick /> use picked face
                </Button>
                {note && <span className="text-[11px] text-muted-foreground">{note}</span>}
              </div>
            )}
          </Field>
        ))}
        {serverError && (
          <p role="alert" className="border-2 border-fail px-2 py-1 text-[11px] text-fail">
            {serverError}
          </p>
        )}
      </div>
      <DialogFooter>
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          cancel
        </Button>
        <Button type="button" size="sm" disabled={busy || (touched && invalid)} onClick={() => void submit()}>
          {busy ? "working…" : editing ? "apply" : "add"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

/** Whether the target slot is shown as the one line "Combined with: <body>" (its field then needs no label). */
function combineLine(spec: Spec, slot: Slot, form: RawForm, state: CombineState, edit?: FeatureRow): boolean {
  if (!spec.combinable || slot.name !== TARGET_SLOT) return false;
  return targetDisplay(state, edit, typeof form[slot.name] === "string" ? (form[slot.name] as string) : "").kind !== "choose";
}

function Field({
  label,
  unit,
  help,
  error,
  children,
}: {
  label: string;
  unit?: string;
  help?: string;
  error?: string | null;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      {label && (
        <Label>
          {label}
          {unit ? ` (${unit})` : ""}
        </Label>
      )}
      {children}
      {help && !error && <span className="text-[11px] text-muted-foreground">{help}</span>}
      {error && <span className="text-[11px] text-fail">{error}</span>}
    </div>
  );
}

function SlotWidget({
  slot,
  form,
  set,
  invalid,
  bodies,
  selection,
  state,
  onProfile,
  kept,
  picks,
  options,
  sketches,
  armed,
  onArm,
  flip,
  onFlip,
  edit,
  combine,
}: {
  edit?: FeatureRow;
  /** The bodies the operation and target controls describe. */
  combine: CombineState;
  sketches: DialogSketches;
  armed: boolean;
  onArm: (armed: boolean) => void;
  flip: { against: boolean; axis: string; can: boolean } | null;
  onFlip: () => void;
  slot: Slot;
  form: RawForm;
  set: (slot: string, value: RawForm[string]) => void;
  invalid: boolean;
  bodies: { name: string; open: boolean }[];
  selection: SelectionItem[];
  state: FeatureState;
  onProfile: (name: string) => void;
  kept: boolean;
  picks: number;
  options?: SlotOption[];
}) {
  const raw = form[slot.name];
  if (slot.kind === "enum" && slot.name === OPERATION_SLOT && slot.options?.some((option) => option.value === "join")) {
    const { options: choices, note } = operationOptions(slot.options, combine, edit);
    return <OperationChooser options={choices} value={typeof raw === "string" ? raw : ""} onChange={(value) => set(slot.name, value)} icons={OPERATION_ICONS} label={slot.label} note={note} />;
  }
  if (slot.kind === "body" && slot.name === TARGET_SLOT) {
    const shown = targetDisplay(combine, edit, typeof raw === "string" ? raw : "");
    if (shown.kind === "hidden") return null;
    if (shown.kind === "fixed") {
      return (
        <span className="text-[12px]" data-testid="combined-with">
          Combined with: <span className="text-name">{shown.name}</span>
        </span>
      );
    }
  }
  switch (slot.kind) {
    case "bool":
      return <Switch checked={Boolean(raw)} onCheckedChange={(checked) => set(slot.name, checked)} />;
    case "enum":
      return (
        <div className="flex flex-col gap-1">
          <Select value={typeof raw === "string" ? raw : ""} onValueChange={(value) => set(slot.name, value)}>
            <SelectTrigger aria-invalid={invalid}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(options ?? slot.options ?? []).map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {flip && (
            <div className="flex items-center gap-2" data-testid="direction-flip" data-against={flip.against}>
              <Button type="button" size="sm" variant="outline" className="h-6 px-2" data-testid="flip-direction" disabled={!flip.can} title="Push the other way (the arrow in the viewport turns)" onClick={onFlip}>
                <ArrowUpDown /> flip
              </Button>
              <span className="text-[11px] text-muted-foreground">
                pushes <span className="text-focus">{flip.against ? "against" : "along"}</span> the sketch normal ({flip.axis}); the arrow in the viewport shows it
              </span>
            </div>
          )}
        </div>
      );
    case "body": {
      const open = bodies.filter((body) => body.open);
      const used = bodies.filter((body) => !body.open);
      return (
        <Select value={typeof raw === "string" ? raw : ""} onValueChange={(value) => set(slot.name, value)}>
          <SelectTrigger aria-invalid={invalid}>
            <SelectValue placeholder="no body yet" />
          </SelectTrigger>
          <SelectContent>
            {open.length > 0 && (
              <SelectGroup>
                <SelectLabel>open bodies</SelectLabel>
                {open.map((body) => (
                  <SelectItem key={body.name} value={body.name}>
                    {body.name}
                  </SelectItem>
                ))}
              </SelectGroup>
            )}
            {used.length > 0 && (
              <SelectGroup>
                <SelectLabel>already used</SelectLabel>
                {used.map((body) => (
                  <SelectItem key={body.name} value={body.name}>
                    {body.name}
                  </SelectItem>
                ))}
              </SelectGroup>
            )}
          </SelectContent>
        </Select>
      );
    }
    case "profile": {
      const profiles = state.profiles ?? [];
      const chosen = typeof raw === "string" ? findProfile(state, raw) : undefined;
      const info = chosen ? sketches.infos.find((item) => item.name === chosen.name) : undefined;
      const loops = chosen ? sketches.shapes.get(chosen.name)?.shape.loopCount ?? 0 : 0;
      const summary = info ? profileSummary(info.doc, loops) : null;
      return (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2 border-2 border-input px-2 py-1" data-testid="sketch-field" data-armed={armed}>
            <span className="min-w-0 flex-1 truncate text-[12px]">
              Sketch: {chosen ? <span className="text-name">{chosen.name}</span> : <span className="text-muted-foreground">none picked</span>}
            </span>
            <Button type="button" size="sm" variant={armed ? "default" : "outline"} className="h-6 px-2" data-testid="sketch-pick" aria-pressed={armed} title="Click a sketch in the viewport or the features list to use it" onClick={() => onArm(!armed)}>
              <Crosshair /> {armed ? "picking…" : "pick in viewport"}
            </Button>
          </div>
          <Select value={typeof raw === "string" ? raw : ""} onValueChange={onProfile}>
            <SelectTrigger aria-invalid={invalid} aria-label="Sketch (list)">
              <SelectValue placeholder="no sketch yet" />
            </SelectTrigger>
            <SelectContent>
              {profiles.map((profile) => (
                <SelectItem key={profile.name} value={profile.name}>
                  {profile.name} ({profilePlaneLabel(profile)})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {chosen && (
            <span className="text-[11px] text-muted-foreground">
              Plane {profilePlaneLabel(chosen)}, normal <span className="text-name">{chosen.normal}</span>
            </span>
          )}
          {summary && (
            <span className="text-[11px] text-muted-foreground" data-testid="profile-summary">
              This sketch has several loops; it uses what was chosen in the sketch ({summary}).
            </span>
          )}
        </div>
      );
    }
    case "point": {
      const parts = Array.isArray(raw) ? raw : ["", "", ""];
      return (
        <div className="grid grid-cols-3 gap-1">
          {["x", "y", "z"].map((axis, index) => (
            <Input
              key={axis}
              aria-label={`${slot.label} ${axis}`}
              inputMode="decimal"
              value={parts[index] ?? ""}
              aria-invalid={invalid}
              placeholder={axis}
              onChange={(event) => set(slot.name, parts.map((part, i) => (i === index ? event.target.value : part)))}
            />
          ))}
        </div>
      );
    }
    case "points2d":
    case "points3d":
      return (
        <Textarea
          rows={5}
          spellCheck={false}
          value={typeof raw === "string" ? raw : ""}
          aria-invalid={invalid}
          placeholder={slot.kind === "points2d" ? "x, y\nx, y\nx, y" : "x, y, z\nx, y, z"}
          onChange={(event) => set(slot.name, event.target.value)}
        />
      );
    case "select": {
      const noun = slot.entity === "edge" ? "Edges" : "Faces";
      const loading = filterSelection(selection, slot.entity ?? "face").some((item) => !isDescribed(item));
      return (
        <div className="flex flex-col gap-1 border-2 border-input px-2 py-1.5">
          <span className="text-[12px]">
            {kept ? (
              <>
                {noun}: <span className="text-muted-foreground">kept from the recipe</span>
              </>
            ) : (
              <>
                {noun}: <span className="text-focus">{picks} picked</span>
                {loading && <span className="text-muted-foreground"> (loading details…)</span>}
              </>
            )}
          </span>
          <span className="text-[11px] text-muted-foreground">
            Pick {noun.toLowerCase()} in the viewport; Ctrl/Cmd+click adds.{kept ? " Pick again to replace them." : ""}
          </span>
        </div>
      );
    }
    default:
      return (
        <div className="relative">
          <Input
            inputMode={slot.kind === "count" ? "numeric" : "decimal"}
            value={typeof raw === "string" ? raw : ""}
            aria-invalid={invalid}
            className={slot.unit ? "pr-10" : undefined}
            onChange={(event) => set(slot.name, event.target.value)}
          />
          {slot.unit && (
            <span className="pointer-events-none absolute inset-y-0 right-2 flex items-center text-[10px] uppercase text-muted-foreground">
              {slot.unit}
            </span>
          )}
        </div>
      );
  }
}
