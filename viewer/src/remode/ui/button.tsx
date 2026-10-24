import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from './lib/utils';

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md text-[11px] font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-lime/60 disabled:pointer-events-none disabled:opacity-40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
  {
    variants: {
      variant: {
        default: 'bg-lime font-semibold text-void hover:bg-lime/85',
        outline: 'border border-edge bg-panel/60 text-dim hover:border-lime/50 hover:text-lime',
        ghost: 'text-dim hover:bg-white/5 hover:text-ink',
        secondary: 'bg-inset border border-line text-ink hover:border-edge',
      },
      size: {
        default: 'h-8 px-3',
        sm: 'h-7 px-2.5',
        icon: 'size-7',
      },
    },
    defaultVariants: {
      variant: 'outline',
      size: 'default',
    },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<'button'> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : 'button';
  return <Comp data-slot="button" className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}

export { Button, buttonVariants };
