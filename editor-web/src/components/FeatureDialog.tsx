import { useEffect, useMemo, useState } from "react";
import { MousePointerClick } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectLabel, SelectGroup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
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

export type DialogRequest = { spec: Spec; edit?: FeatureRow };

/** The form of one operation, generated from its spec.  A docked card, not a modal: the viewport stays live. */
export function FeatureDialog({
  request,
  state,
  selection,
  onSelectionMode,
  onSubmit,
  onClose,
}: {
  request: DialogRequest | null;
  state: FeatureState;
  selection: SelectionItem[];
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
  onSelectionMode,
  onSubmit,
  onClose,
}: {
  request: DialogRequest;
  state: FeatureState;
  selection: SelectionItem[];
  onSelectionMode: (mode: SelectionMode) => void;
  onSubmit: (command: FeatureCommand) => Promise<void>;
  onClose: () => void;
}) {
  const { spec, edit } = request;
  const editing = Boolean(edit);
  const [form, setForm] = useState<RawForm>(() => {
    const initial = initialForm(spec, state.defaults[spec.id] ?? {}, edit?.gui?.values ?? {});
    // A new feature on a sketch pushes along that sketch's plane normal.
    const profileSlot = spec.slots.find((slot) => slot.kind === "profile");
    const normal = !edit && profileSlot && typeof initial[profileSlot.name] === "string" ? directionForProfile(state, initial[profileSlot.name] as string) : null;
    return normal && spec.slots.some((slot) => slot.name === "direction") ? { ...initial, direction: normal } : initial;
  });
  const [name, setName] = useState(edit?.slug ?? "");
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  // Picks present when the form opened: in edit mode only a different pick replaces the recipe.
  const [initialKeys] = useState(() => new Set(selection.map((item) => item.key)));
  const selectSlots = spec.slots.filter((slot) => slot.kind === "select");
  const picksOf = (slot: Slot) => filterSelection(selection, slot.entity ?? "face");
  const replaced = (slot: Slot) => {
    const keys = picksOf(slot).map((item) => item.key);
    if (!keys.length) return false;
    return !editing || keys.length !== initialKeys.size || keys.some((key) => !initialKeys.has(key));
  };

  // The viewport picks what the form asks for while it is open, and goes back after.
  const wanted = (selectSlots[0]?.entity ?? (spec.id === "hole" ? "face" : null)) as SelectionMode | null;
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
    () => (typeof formValues.direction === "string" ? { ...formValues, direction: resolveDirection(formValues.direction, state, profileName) } : formValues),
    [formValues, state, profileName],
  );
  const errors = formErrors;
  const nameError = editing ? null : validateName(name, state.taken);
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
      : { op: "add", spec: spec.id, ...(name.trim() ? { name: name.trim() } : {}), values, ...withSelections };
    try {
      await onSubmit(command);
    } catch (error) {
      setServerError(error instanceof Error ? error.message : String(error));
      setBusy(false);
    }
  };

  const useFace = () => {
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
          {editing ? "Edit" : "Add"} {spec.label.toLowerCase()}
        </DialogTitle>
        <DialogDescription>{spec.description}</DialogDescription>
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
        {spec.slots.map((slot) => (
          <Field key={slot.name} label={slot.label} unit={slot.kind === "point" ? slot.unit : undefined} help={spec.id === "hole" && slot.name === "position" && note ? undefined : slot.help} error={touched ? (allErrors[slot.name] ?? null) : null}>
            <SlotWidget
              slot={slot}
              form={form}
              set={set}
              invalid={touched && Boolean(errors[slot.name])}
              bodies={bodies}
              selection={selection}
              state={state}
              onProfile={(name) => {
                const normal = directionForProfile(state, name);
                setForm((previous) => ({ ...previous, [slot.name]: name, ...(normal && spec.slots.some((other) => other.name === "direction") ? { direction: normal } : {}) }));
                setServerError(null);
              }}
              kept={editing && !replaced(slot)}
              picks={slot.kind === "select" ? picksOf(slot).length : 0}
              options={slot.name === "direction" && slot.kind === "enum" ? directionOptions(slot.options ?? [], state, profileName) : undefined}
            />
            {spec.id === "hole" && slot.name === "position" && (
              <div className="mt-1 flex flex-col gap-1">
                <Button type="button" size="sm" variant="outline" onClick={useFace}>
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
      <Label>
        {label}
        {unit ? ` (${unit})` : ""}
      </Label>
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
}: {
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
  switch (slot.kind) {
    case "bool":
      return <Switch checked={Boolean(raw)} onCheckedChange={(checked) => set(slot.name, checked)} />;
    case "enum":
      return (
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
      return (
        <div className="flex flex-col gap-1">
          <Select value={typeof raw === "string" ? raw : ""} onValueChange={onProfile}>
            <SelectTrigger aria-invalid={invalid}>
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
