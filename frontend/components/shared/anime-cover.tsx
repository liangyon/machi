/**
 * Anime cover image with fallback placeholder.
 * Used in recommendation cards, watchlist cards, and dashboard top-10.
 */

interface AnimeCoverProps {
  src: string | null;
  alt: string;
  className?: string;
  fallbackClassName?: string;
}

export function AnimeCover({
  src,
  alt,
  className = "h-full w-full object-cover",
  fallbackClassName = "flex h-full items-center justify-center bg-muted text-xs text-muted-foreground",
}: AnimeCoverProps) {
  if (src) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={src} alt={alt} className={className} />
    );
  }

  return <div className={fallbackClassName}>No image</div>;
}
