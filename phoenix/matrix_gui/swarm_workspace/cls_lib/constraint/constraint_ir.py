class ConstraintIR:
    def __init__(self, cname, category, full, slice_, path):
        self.cname = cname
        self.category = category
        self.full = full
        self.slice = slice_
        self.path = path or []