export function DisplayEmptyState({ message }: { message: string }) {
  return (
    <div className="flex h-full min-h-[40vh] items-center justify-center">
      <p className="text-2xl text-white/40">{message}</p>
    </div>
  );
}
