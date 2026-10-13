import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center border px-1.5 py-px text-[10px] font-semibold uppercase leading-4 tracking-[0.08em]",
  {
    variants: {
      variant: {
        default: "border-white bg-white text-black",
        secondary: "border-input text-muted-foreground",
        outline: "border-input text-foreground",
        focus: "border-focus text-focus",
        pass: "border-pass text-pass",
        fail: "border-fail text-fail",
        name: "border-name text-name",
        destructive: "border-fail bg-fail text-black",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
