/**
 * Auth Layout — wraps /login and /register pages
 * Centered card layout, no navbar.
 */
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      {children}
    </div>
  );
}
