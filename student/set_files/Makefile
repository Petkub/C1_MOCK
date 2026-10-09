# Linux / macOS, inside this Mock folder:
#   make      judge the whole set (1.cpp ... 8.cpp)
#   make 5    judge problem 5 only
PYTHON ?= python3
JUDGE  := $(PYTHON) ../Judge/judge.py

all:
	@$(JUDGE)

1 2 3 4 5 6 7 8:
	@$(JUDGE) $@.cpp

.PHONY: all 1 2 3 4 5 6 7 8
