"""PR data adapter, restricted to the current public repository."""
import json
from .github import GitHub as ReadOnlyGitHub

class GitHub(ReadOnlyGitHub):
    def pr(self,number):
        return self.call(f'/pulls/{number}')

    def changed_files(self,number):
        return self.pages(f'/pulls/{number}/files')

    def reviews(self,number):
        return self.pages(f'/pulls/{number}/reviews',max_pages=2)

    def commit(self,sha):
        return self.call(f'/commits/{sha}')

    def record(self,number,marker,receipt):
        comments=self.pages(f'/issues/{number}/comments',max_pages=2)
        if any(marker in c.get('body','') for c in comments):
            return False
        self.call(f'/issues/{number}/comments','POST',{
            'body':'<!-- smart-pr-merge-receipt -->\n'+marker+
                   '\n'+json.dumps(receipt,ensure_ascii=False,sort_keys=True)})
        return True
