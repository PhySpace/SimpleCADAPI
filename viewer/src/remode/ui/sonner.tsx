import { Toaster as Sonner, type ToasterProps } from 'sonner';

function Toaster({ ...props }: ToasterProps) {
  return (
    <Sonner
      theme="dark"
      position="bottom-right"
      offset={18}
      toastOptions={{
        style: {
          background: 'rgba(16, 20, 26, 0.92)',
          border: '1px solid #2a3440',
          color: '#dfe7f1',
          backdropFilter: 'blur(10px)',
          fontSize: '11px',
        },
      }}
      {...props}
    />
  );
}

export { Toaster };
