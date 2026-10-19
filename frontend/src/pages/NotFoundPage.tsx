import { Link } from 'react-router-dom';
import { PagePlaceholder } from '../components/PagePlaceholder';

export function NotFoundPage() {
  return (
    <div>
      <PagePlaceholder title="Page not found" description="That page does not exist." />
      <Link to="/" className="mt-4 inline-block text-primary underline">
        Back to home
      </Link>
    </div>
  );
}
