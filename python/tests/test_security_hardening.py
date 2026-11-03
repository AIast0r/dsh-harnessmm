import json
import pytest
from dsh_harnessmm_rsi.runner import load_corpus


@pytest.mark.parametrize('name', [
    'C:/Users/Admin/.dsh/config.json',
    'C:escape.py',
    'C\\escape.py',
    '..\\outside.py',
    '//server/share/secret.py',
    'CON.py',
    'dir/NUL.txt',
    'trailing. ',
])
def test_rejects_windows_unsafe_seed_paths(name, tmp_path):
    corpus={'schema':'dsh-harnessmm-corpus/v1','name':'local-safety',
            'tasks':[{'id':'one','unit_id':'one','public_prompt':'safe',
                      'seed_files':{name:'value'},'verifier_argv':['python3','-c','pass']}]}
    source=tmp_path/'corpus.json';source.write_text(json.dumps(corpus))
    with pytest.raises(ValueError,match='unsafe seed file path'):
        load_corpus(source)


def test_accepts_safe_nested_path(tmp_path):
    corpus={'schema':'dsh-harnessmm-corpus/v1','name':'local-safety',
            'tasks':[{'id':'one','unit_id':'one','public_prompt':'safe',
                      'seed_files':{'src/solution.py':'value'},'verifier_argv':['python3','-c','pass']}]}
    source=tmp_path/'corpus.json';source.write_text(json.dumps(corpus))
    assert load_corpus(source)['tasks'][0]['seed_files']['src/solution.py']=='value'
