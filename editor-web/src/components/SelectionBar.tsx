import type { LucideIcon } from "lucide-react";
import { useMemo, useRef } from "react";

import { ActionBar } from "@/components/ActionBar";
import { useViewer } from "@/components/sketch/SketchOverlay";
import { contextualActions, type Command, type SelectionContext } from "@/lib/commands";
import type { Vec3 } from "@/lib/sketch-plane";
import { worldToScreen } from "@/lib/sketch-view";
import type { SceneView } from "@/scene/scene-view";

/** The contextual actions of the selection, from the command registry (see CONTEXT_ACTIONS and the commands' `when`),
 * hung near the selection in the viewport. */
export function SelectionBar({
  view,
  commands,
  context,
  anchorMm,
  icons = {},
  notice,
  disabled,
  title,
}: {
  view: SceneView;
  commands: readonly Command[];
  context: SelectionContext;
  anchorMm: Vec3 | null;
  icons?: Record<string, LucideIcon>;
  notice?: string | null;
  /** Reasons by command id why an action cannot run now. */
  disabled?: Readonly<Record<string, string>>;
  title?: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const { viewer, size } = useViewer(view, host);
  const actions = useMemo(
    () =>
      contextualActions(commands, context).map(({ command, label }) => ({
        id: command.id,
        label,
        icon: icons[command.id] ?? command.icon,
        hint: command.description,
        disabled: disabled?.[command.id] ?? null,
        run: command.run,
      })),
    [commands, context, icons, disabled],
  );
  const anchor = anchorMm ? worldToScreen(viewer, anchorMm) : null;
  return (
    <div ref={host} className="pointer-events-none absolute inset-0 z-10" data-testid="selection-bar">
      <ActionBar actions={actions} anchor={anchor} bounds={size} title={title} notice={notice} />
    </div>
  );
}
