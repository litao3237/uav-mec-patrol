"""P30 exact strict witness must originate from previously archived P29."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))
from run_p30_crossrunner_witness_verification import (
    WITNESS_SHA,SCENE,SEED,PROFILE,TARGET_TASK,TARGET_OWNER,TARGET_CONTACT,
)


def test_original_p29_witness_is_frozen_and_complete_sha():
    assert len(WITNESS_SHA)==64
    assert WITNESS_SHA=="e2e7d90260a5fe6d9e2139f359fdcb9039a4b79b690905d9af35bbfe873998a5"
    assert (SCENE,PROFILE,SEED)==(91,"compute_x1p5",128)
    assert (TARGET_TASK,TARGET_OWNER,TARGET_CONTACT)==("S36","U1","G_U1_1")
