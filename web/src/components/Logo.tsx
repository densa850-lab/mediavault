/** Original MediaVault mark: a rounded vault door with a play triangle. */
export function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="MediaVault logo">
      <rect x="1" y="1" width="30" height="30" rx="8" fill="#0B1F3A" />
      <circle cx="16" cy="16" r="9" fill="none" stroke="#3B82F6" strokeWidth="2.5" />
      <path d="M14 11.5 L21 16 L14 20.5 Z" fill="#FFFFFF" />
    </svg>
  );
}
