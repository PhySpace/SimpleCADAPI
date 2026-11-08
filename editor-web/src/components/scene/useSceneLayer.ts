import { useEffect, useState } from "react";

import { layerHostFor, type LayerViewLike, type SceneLayer } from "@/scene/layers/layer-host";

/** React lifecycle of a scene layer: the layer `name` of `view`'s layer host, created when the view is there and
 * removed when the component unmounts or the view changes.  Returns null until then.  The returned layer is stable
 * for the view's lifetime, so effects may depend on it. */
export function useSceneLayer(view: LayerViewLike | null | undefined, name: string): SceneLayer | null {
  const [layer, setLayer] = useState<SceneLayer | null>(null);
  useEffect(() => {
    if (!view) return;
    const host = layerHostFor(view);
    const created = host.layer(name);
    setLayer(created);
    return () => {
      created.dispose();
      setLayer(null);
    };
  }, [view, name]);
  return view ? layer : null;
}
