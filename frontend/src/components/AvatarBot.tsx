interface Props {
  size?: number;
  className?: string;
}

// A soft gradient "AI orb" — purely CSS/SVG, no images required.
export default function AvatarBot({ size = 36, className }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <radialGradient id="bot-grad" cx="50%" cy="40%" r="65%">
          <stop offset="0%" stopColor="#fdfbff" />
          <stop offset="45%" stopColor="#d8c9ff" />
          <stop offset="100%" stopColor="#a59cff" />
        </radialGradient>
        <linearGradient id="bot-rim" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#ffd4f0" />
          <stop offset="50%" stopColor="#c9b8ff" />
          <stop offset="100%" stopColor="#9bd2ff" />
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r="30" fill="url(#bot-rim)" opacity="0.55" />
      <circle cx="32" cy="32" r="24" fill="url(#bot-grad)" />
      <circle cx="32" cy="32" r="14" fill="#a78bff" opacity="0.85" />
      <circle cx="27" cy="31" r="2.4" fill="#fff" />
      <circle cx="37" cy="31" r="2.4" fill="#fff" />
      <rect x="25" y="36" width="14" height="3" rx="1.5" fill="#fff" opacity="0.9" />
    </svg>
  );
}